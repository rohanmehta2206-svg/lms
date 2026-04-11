import os
import time

from django.conf import settings
from django.http import FileResponse, Http404, JsonResponse, HttpResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.contrib import messages

import json
import base64
from django.core.files.base import ContentFile

from reportlab.lib.pagesizes import landscape, A4
from reportlab.lib.colors import HexColor, white
from reportlab.pdfgen import canvas
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF

from teacher.models import Course, Section, Module, CertificateSettings
from teacher.views import build_signed_stream_url
from teacher.moodle_api import (
    enroll_student_to_course,
    mark_moodle_activity_complete,
    get_single_activity_completion_state,
    issue_moodle_certificate_record,
    update_moodle_user_profile_from_django_user,
)
from .models import (
    Enrollment,
    StudentModuleProgress,
    QuizAttempt,
    Student,
    StudentCertificate,
    VideoWatchProgress,
    VideoWatchEvent,
    WebcamSnapshot,
    TabSwitchLog,
)
from accounts.models import UserProfile
from django.views.decorators.http import require_POST


# =====================================
# HELPER: FIND REAL FILE PATH SAFELY
# =====================================
def get_real_material_path(field_file):
    if not field_file:
        return None

    relative_path = str(field_file).replace("/", os.sep)

    possible_paths = [
        os.path.join(r"C:\lms_storage", relative_path),
        os.path.join(r"C:\Users\rohan\OneDrive\Documents\teacher\instructor\media", relative_path),
    ]

    for path in possible_paths:
        if os.path.exists(path):
            return path

    return None


# =====================================
# HELPER: ENROLLMENT CHECK
# =====================================
def is_student_enrolled(user, course):
    return Enrollment.objects.filter(
        student=user,
        course=course,
        is_active=True
    ).exists()


def get_active_enrollment(user, course):
    return Enrollment.objects.filter(
        student=user,
        course=course,
        is_active=True
    ).order_by("-id").first()


def get_student_active_course_ids(user):
    return list(
        Enrollment.objects.filter(
            student=user,
            is_active=True,
            course__is_published=True
        )
        .values_list("course_id", flat=True)
        .distinct()
    )


def get_student_active_courses(user):
    course_ids = get_student_active_course_ids(user)

    return Course.objects.filter(
        id__in=course_ids,
        is_published=True
    ).order_by("-created_at")


def get_course_sections(course):
    return list(
        Section.objects.filter(course=course).order_by("order")
    )


# =====================================
# HELPER: LOCK / UNLOCK MODULE FLOW
# =====================================
def get_ordered_course_modules(course):
    return list(
        Module.objects.filter(
            section__course=course,
            is_published=True
        )
        .select_related("section", "section__course")
        .order_by("section__order", "order", "id")
    )


def get_completed_module_ids(user, course):
    course_module_ids = list(
    Module.objects.filter(
        section__course=course,
        is_published=True
    ).values_list("id", flat=True).distinct()
)

    return set(
        StudentModuleProgress.objects.filter(
            student=user,
            module_id__in=course_module_ids,
            is_completed=True
        ).values_list("module_id", flat=True).distinct()
    )


def get_next_unlocked_module_id(user, course):
    ordered_modules = get_ordered_course_modules(course)
    completed_module_ids = get_completed_module_ids(user, course)

    if not ordered_modules:
        return None

    for module in ordered_modules:
        if module.id not in completed_module_ids:
            return module.id

    return None


def get_locked_module_ids(user, course):
    """
    Strict guided flow:
    - completed modules before the first pending module stay open
    - first pending module stays unlocked
    - every module after the first pending module stays locked
    """
    ordered_modules = get_ordered_course_modules(course)
    completed_module_ids = get_completed_module_ids(user, course)

    locked_module_ids = set()
    first_pending_found = False

    for module in ordered_modules:
        if not first_pending_found:
            if module.id in completed_module_ids:
                continue

            # first incomplete module = current unlocked module
            first_pending_found = True
            continue

        # everything after first pending stays locked
        locked_module_ids.add(module.id)

    return locked_module_ids


def is_module_locked(user, module):
    course = module.section.course
    locked_module_ids = get_locked_module_ids(user, course)
    return module.id in locked_module_ids


# =====================================
# HELPER: COURSE ACCESS CHECK
# =====================================
def ensure_course_access(request, course):
    if not is_student_enrolled(request.user, course):
        messages.error(request, "You are not enrolled in this course.")
        return False
    return True


def ensure_module_access(request, module):
    course = module.section.course

    if not is_student_enrolled(request.user, course):
        messages.error(request, "You are not enrolled in this course.")
        return False

    if is_module_locked(request.user, module):
        messages.warning(request, "This module is locked. Please complete the current unlocked module first.")
        return False

    return True


# =====================================
# HELPER: COURSE PROGRESS DATA
# =====================================
def get_course_progress_data(user, course, sections):
    module_ids = []

    for section in sections:
        section_module_ids = list(
            section.modules.filter(
                is_published=True
            ).values_list("id", flat=True).distinct()
        )
        module_ids.extend(section_module_ids)

    module_ids = list(dict.fromkeys(module_ids))
    total_modules = len(module_ids)

    completed_module_ids = set(
        StudentModuleProgress.objects.filter(
            student=user,
            module_id__in=module_ids,
            is_completed=True
        ).values_list("module_id", flat=True).distinct()
    )

    completed_modules = len(completed_module_ids)
    pending_modules = total_modules - completed_modules

    progress_percent = 0
    if total_modules > 0:
        progress_percent = int((completed_modules / total_modules) * 100)

    return {
        "total_modules": total_modules,
        "completed_modules": completed_modules,
        "pending_modules": pending_modules,
        "progress_percent": progress_percent,
        "completed_module_ids": completed_module_ids,
    }


# =====================================
# HELPER: CERTIFICATE LOGIC
# =====================================
def is_course_completed_by_student(user, course):
    sections = get_course_sections(course)
    progress_data = get_course_progress_data(user, course, sections)
    return progress_data["total_modules"] > 0 and progress_data["progress_percent"] == 100


def get_certificate_id(user, course):
    return f"CERT-{course.id}-{user.id}"


def get_certificate_student_name(user):
    full_name = user.get_full_name().strip()
    if full_name:
        return full_name
    return getattr(user, "username", "Student")


def get_certificate_verification_url(request, course, user):
    verify_path = f"/student/certificate/verify/{course.id}/{user.id}/"
    if request:
        return request.build_absolute_uri(verify_path)
    return verify_path


def get_or_create_student_certificate(request, user, course):
    certificate_code = get_certificate_id(user, course)
    student_name = get_certificate_student_name(user)
    verification_url = get_certificate_verification_url(request, course, user)

    certificate_obj, created = StudentCertificate.objects.get_or_create(
        student=user,
        course=course,
        defaults={
            "certificate_code": certificate_code,
            "student_name": student_name,
            "course_title": str(course.title),
            "verification_url": verification_url,
            "status": StudentCertificate.STATUS_ISSUED,
        }
    )

    needs_update = False

    if certificate_obj.certificate_code != certificate_code:
        certificate_obj.certificate_code = certificate_code
        needs_update = True

    if certificate_obj.student_name != student_name:
        certificate_obj.student_name = student_name
        needs_update = True

    if certificate_obj.course_title != str(course.title):
        certificate_obj.course_title = str(course.title)
        needs_update = True

    if certificate_obj.verification_url != verification_url:
        certificate_obj.verification_url = verification_url
        needs_update = True

    if certificate_obj.status != StudentCertificate.STATUS_ISSUED and not certificate_obj.is_revoked:
        certificate_obj.status = StudentCertificate.STATUS_ISSUED
        needs_update = True

    if needs_update:
        certificate_obj.save()

    return certificate_obj


def get_completed_courses_for_certificates(user):
    completed_rows = []
    courses = get_student_active_courses(user)

    existing_certificates = {
        cert.course_id: cert
        for cert in StudentCertificate.objects.filter(student=user).select_related("course")
    }

    for course in courses:
        sections = get_course_sections(course)
        progress_data = get_course_progress_data(user, course, sections)

        if progress_data["total_modules"] > 0 and progress_data["progress_percent"] == 100:
            certificate_obj = existing_certificates.get(course.id)

            completed_rows.append({
                "course": course,
                "total_modules": progress_data["total_modules"],
                "completed_modules": progress_data["completed_modules"],
                "progress_percent": progress_data["progress_percent"],
                "certificate_id": get_certificate_id(user, course),
                "certificate_obj": certificate_obj,
                "issued_at": certificate_obj.issued_at if certificate_obj else None,
                "moodle_certificate_id": certificate_obj.moodle_certificate_id if certificate_obj else None,
                "moodle_sync_status": certificate_obj.moodle_sync_status if certificate_obj else "Not Synced",
                "status": certificate_obj.status if certificate_obj else "issued",
            })

    return completed_rows


def try_issue_certificate_record_to_moodle(request, user, course, certificate_obj=None):
    """
    Best-effort sync:
    - Django remains certificate generator
    - Moodle stores certificate issue record
    - returned Moodle certificate record id is saved into StudentCertificate
    """
    try:
        moodle_user_id = get_user_moodle_id(user)
        moodle_course_id = getattr(course, "moodle_course_id", None)
        certificate_id = get_certificate_id(user, course)

        if not moodle_user_id:
            return {
                "success": False,
                "message": "Moodle user id is missing.",
                "moodle_certificate_id": None,
            }

        if not moodle_course_id:
            return {
                "success": False,
                "message": "Moodle course id is missing.",
                "moodle_certificate_id": None,
            }

        certificate_url = get_certificate_verification_url(request, course, user)
        issuedate = int(time.time())

        ok, error, moodle_certificate_id = issue_moodle_certificate_record(
            moodle_user_id=moodle_user_id,
            moodle_course_id=moodle_course_id,
            certificate_id=certificate_id,
            certificate_url=certificate_url,
            issuedate=issuedate,
        )

        if certificate_obj:
            if ok:
                certificate_obj.moodle_certificate_id = str(moodle_certificate_id or "").strip() or None
                certificate_obj.moodle_sync_status = "Synced"
            else:
                certificate_obj.moodle_sync_status = "Not Synced"
            certificate_obj.save(update_fields=["moodle_certificate_id", "moodle_sync_status"])

        if ok:
            return {
                "success": True,
                "message": "Certificate issue record stored in Moodle successfully.",
                "moodle_certificate_id": moodle_certificate_id,
            }

        return {
            "success": False,
            "message": error or "Could not store certificate issue record in Moodle.",
            "moodle_certificate_id": None,
        }

    except Exception as e:
        if certificate_obj:
            certificate_obj.moodle_sync_status = "Not Synced"
            certificate_obj.save(update_fields=["moodle_sync_status"])

        return {
            "success": False,
            "message": f"Moodle certificate sync error: {str(e)}",
            "moodle_certificate_id": None,
        }

def get_active_certificate_settings():
    settings_obj = CertificateSettings.objects.filter(is_active=True).order_by("-updated_at", "-id").first()

    if settings_obj:
        return settings_obj

    return None

def draw_certificate_pdf(response, user, course, request=None):
    page_width, page_height = landscape(A4)
    pdf = canvas.Canvas(response, pagesize=landscape(A4))

    certificate_settings = get_active_certificate_settings()

    border_blue = HexColor("#4fb6d6")
    text_dark = HexColor("#1f2937")
    text_mid = HexColor("#374151")
    soft_gray = HexColor("#6b7280")
    gold = HexColor("#e6c44f")
    bg = HexColor("#ffffff")

    pdf.setFillColor(bg)
    pdf.rect(0, 0, page_width, page_height, fill=1, stroke=0)

    # Outer border
    pdf.setStrokeColor(border_blue)
    pdf.setLineWidth(3)
    pdf.rect(32, 32, page_width - 64, page_height - 64, stroke=1, fill=0)

    # Inner border
    pdf.setLineWidth(1.5)
    pdf.rect(44, 44, page_width - 88, page_height - 88, stroke=1, fill=0)

    # Small top line
    pdf.setLineWidth(3)
    pdf.line(70, page_height - 38, page_width - 70, page_height - 38)

    # Dynamic certificate settings
    certificate_title = "Certificate of Completion"
    certificate_subtitle = "This certificate is proudly presented to"
    organization_name = "Cryptographic Adaptive LMS"
    issuer_name = "Instructor"
    signer_name = "Authorized Signature"
    signer_role = "Instructor"
    verify_label = "Verify via LMS QR record"
    signature_path = os.path.join(settings.MEDIA_ROOT, "signature.png")
    seal_path = os.path.join(settings.MEDIA_ROOT, "seal.png")

    if certificate_settings:
        certificate_title = certificate_settings.title or certificate_title
        certificate_subtitle = certificate_settings.subtitle or certificate_subtitle
        organization_name = certificate_settings.organization_name or organization_name
        issuer_name = certificate_settings.issuer_name or issuer_name
        signer_name = certificate_settings.signer_name or signer_name
        signer_role = certificate_settings.signer_role or signer_role
        verify_label = certificate_settings.verify_label or verify_label

        if certificate_settings.signature_image:
            try:
                signature_path = certificate_settings.signature_image.path
            except Exception:
                pass

        if certificate_settings.seal_image:
            try:
                seal_path = certificate_settings.seal_image.path
            except Exception:
                pass

    student_name = get_certificate_student_name(user)
    course_title = str(course.title)
    certificate_id = get_certificate_id(user, course)
    completion_date = timezone.localdate().strftime("%d %b %Y")

    if len(course_title) > 40:
        course_title = course_title[:40] + "..."

    verify_url = f"/student/certificate/verify/{course.id}/{user.id}/"
    verification_url = verify_url

    if request:
        verification_url = request.build_absolute_uri(verify_url)

    # Title
    pdf.setFillColor(text_dark)
    pdf.setFont("Times-Italic", 30)
    pdf.drawCentredString(page_width / 2, page_height - 120, certificate_title)

    # Seal on left
    seal_x = 78
    seal_y = page_height - 210

    if os.path.exists(seal_path):
        pdf.drawImage(
            seal_path,
            seal_x,
            seal_y,
            width=95,
            height=50,
            preserveAspectRatio=True,
            mask='auto'
        )
    else:
        pdf.setFillColor(gold)
        pdf.circle(seal_x + 30, seal_y + 25, 24, fill=1, stroke=0)

        pdf.setFillColor(text_mid)
        pdf.setFont("Helvetica", 5)
        pdf.drawCentredString(seal_x + 30, seal_y + 27, "Seal")

    # Name and body text
    pdf.setFillColor(text_mid)
    pdf.setFont("Times-Italic", 16)
    pdf.drawCentredString(page_width / 2, page_height - 182, certificate_subtitle)

    pdf.setFillColor(text_dark)
    pdf.setFont("Times-Bold", 20)
    pdf.drawCentredString(page_width / 2, page_height - 220, student_name)

    pdf.setFillColor(text_mid)
    pdf.setFont("Times-Italic", 16)
    pdf.drawCentredString(page_width / 2, page_height - 248, "has completed")

    pdf.setFillColor(text_dark)
    pdf.setFont("Times-Bold", 21)
    pdf.drawCentredString(page_width / 2, page_height - 285, course_title)

    pdf.setFillColor(text_mid)
    pdf.setFont("Times-Italic", 15)
    pdf.drawCentredString(page_width / 2, page_height - 315, "offered by")

    pdf.setFillColor(text_dark)
    pdf.setFont("Times-Bold", 18)
    pdf.drawCentredString(page_width / 2, page_height - 346, organization_name)

    pdf.setFillColor(text_mid)
    pdf.setFont("Helvetica", 11)
    pdf.drawCentredString(page_width / 2, page_height - 372, f"Issued by: {issuer_name}")

    # QR bottom left
    qr_code = qr.QrCodeWidget(verification_url)
    bounds = qr_code.getBounds()
    qr_width = bounds[2] - bounds[0]
    qr_height = bounds[3] - bounds[1]
    qr_size = 56

    qr_drawing = Drawing(
        qr_size,
        qr_size,
        transform=[qr_size / qr_width, 0, 0, qr_size / qr_height, 0, 0]
    )
    qr_drawing.add(qr_code)

    qr_x = 96
    qr_y = 96
    renderPDF.draw(qr_drawing, pdf, qr_x, qr_y)

    pdf.setFillColor(text_mid)
    pdf.setFont("Helvetica", 9)
    pdf.drawString(160, 137, f"Issued: {completion_date}")
    pdf.drawString(160, 121, f"Certificate No: {certificate_id}")
    pdf.drawString(160, 105, verify_label)

    # Signature area right
    sign_line_x1 = page_width - 275
    sign_line_x2 = page_width - 115
    sign_y = 118

    pdf.setStrokeColor(text_mid)
    pdf.setLineWidth(1)
    pdf.line(sign_line_x1, sign_y, sign_line_x2, sign_y)

    if os.path.exists(signature_path):
        pdf.drawImage(
            signature_path,
            sign_line_x1 + 18,
            sign_y + 8,
            width=120,
            height=40,
            mask='auto'
        )
    else:
        pdf.setFillColor(text_dark)
        pdf.setFont("Times-Italic", 22)
        pdf.drawCentredString((sign_line_x1 + sign_line_x2) / 2, sign_y + 24, signer_name)

    pdf.setFillColor(text_dark)
    pdf.setFont("Helvetica", 10)
    pdf.drawCentredString((sign_line_x1 + sign_line_x2) / 2, sign_y - 14, signer_role)

    # Footer
    pdf.setFillColor(soft_gray)
    pdf.setFont("Helvetica", 9)
    pdf.drawCentredString(page_width / 2, 52, "Generated from Django LMS integrated with Moodle")

    pdf.showPage()
    pdf.save()


def verify_certificate(request, course_id, user_id):
    course = get_object_or_404(Course, id=course_id, is_published=True)
    from django.contrib.auth.models import User
    student_user = get_object_or_404(User, id=user_id)

    certificate_obj = StudentCertificate.objects.filter(
        student=student_user,
        course=course
    ).first()

    is_valid = is_course_completed_by_student(student_user, course)
    is_revoked = bool(certificate_obj and certificate_obj.is_revoked)

    context = {
        "course": course,
        "student_user": student_user,
        "certificate_id": get_certificate_id(student_user, course),
        "is_valid": is_valid and not is_revoked,
        "is_revoked": is_revoked,
        "issued_date": certificate_obj.issued_at if certificate_obj else timezone.localdate(),
        "certificate_obj": certificate_obj,
    }
    return render(request, "student/verify_certificate.html", context)


# =====================================
# HELPER: MARK SINGLE MODULE COMPLETED
# =====================================
def complete_module_for_user(user, module):
    progress_obj, created = StudentModuleProgress.objects.get_or_create(
        student=user,
        module=module,
        defaults={
            "is_completed": True,
            "completed_at": timezone.now()
        }
    )

    if not created and not progress_obj.is_completed:
        progress_obj.is_completed = True
        progress_obj.completed_at = timezone.now()
        progress_obj.save()

    return progress_obj


# =====================================
# HELPER: MOODLE USER ID RESOLVER
# =====================================
def get_user_moodle_id(user):
    moodle_user_id = None
    user_profile = getattr(user, "profile", None)

    if user_profile:
        moodle_user_id = getattr(user_profile, "moodle_user_id", None)

    if moodle_user_id:
        return moodle_user_id

    student_row = Student.objects.filter(user=user).first()
    if student_row and getattr(student_row, "moodle_user_id", None):
        moodle_user_id = student_row.moodle_user_id

        if user_profile:
            if not getattr(user_profile, "moodle_user_id", None):
                user_profile.moodle_user_id = moodle_user_id
                user_profile.save(update_fields=["moodle_user_id"])
        else:
            UserProfile.objects.update_or_create(
                user=user,
                defaults={"moodle_user_id": moodle_user_id}
            )

        return moodle_user_id

    return None


# =====================================
# HELPER: MOODLE COMPLETION SYNC
# =====================================
def get_module_moodle_cmid(module):
    return getattr(module, "moodle_cmid", None)


def _extract_completion_state(row):
    if not isinstance(row, dict):
        return None

    possible_keys = [
        "state",
        "completionstate",
        "status",
    ]

    for key in possible_keys:
        value = row.get(key)
        if value is not None:
            return value

    return None


def try_sync_module_completion_to_moodle(user, module):
    try:
        moodle_user_id = get_user_moodle_id(user)
        moodle_cmid = get_module_moodle_cmid(module)
        moodle_course_id = getattr(module.section.course, "moodle_course_id", None)

        print("\n========== MOODLE COMPLETION SYNC START ==========")
        print("Django user:", getattr(user, "username", None))
        print("Module id:", getattr(module, "id", None))
        print("Module title:", getattr(module, "title", None))
        print("Module type:", getattr(module, "type", None))
        print("Moodle user id:", moodle_user_id)
        print("Moodle cmid:", moodle_cmid)
        print("Moodle course id:", moodle_course_id)

        if not moodle_user_id:
            print("❌ Moodle sync failed: Student Moodle user id is missing.")
            print("========== MOODLE COMPLETION SYNC END ==========\n")
            return {
                "success": False,
                "message": "Student Moodle user id is missing."
            }

        if not moodle_cmid:
            print("❌ Moodle sync failed: Module Moodle cmid is missing.")
            print("========== MOODLE COMPLETION SYNC END ==========\n")
            return {
                "success": False,
                "message": "Module Moodle cmid is missing."
            }

        moodle_ok, moodle_message = mark_moodle_activity_complete(
            moodle_user_id=moodle_user_id,
            cmid=moodle_cmid
        )

        print("mark_moodle_activity_complete() ->", moodle_ok, moodle_message)

        if not moodle_ok:
            print("❌ Moodle sync failed during mark call.")
            print("========== MOODLE COMPLETION SYNC END ==========\n")
            return {
                "success": False,
                "message": moodle_message
            }

        if moodle_course_id:
            verify_ok, verify_error, verify_row = get_single_activity_completion_state(
                moodle_course_id=moodle_course_id,
                moodle_user_id=moodle_user_id,
                cmid=moodle_cmid
            )

            print("Verification status:", verify_ok)
            print("Verification error:", verify_error)
            print("Verification row:", verify_row)

            if verify_ok and isinstance(verify_row, dict):
                state_value = _extract_completion_state(verify_row)

                if str(state_value) in ["1", "2", "complete", "completed"]:
                    print("✅ Moodle sync verified successfully.")
                    print("========== MOODLE COMPLETION SYNC END ==========\n")
                    return {
                        "success": True,
                        "message": "Moodle activity marked as completed successfully."
                    }

                print("❌ Moodle verification did not return completed state.")
                print("========== MOODLE COMPLETION SYNC END ==========\n")
                return {
                    "success": False,
                    "message": "Moodle update call succeeded, but completion is still not showing as completed."
                }

            print("⚠️ Moodle update sent successfully, but verification could not confirm the state.")
            print("========== MOODLE COMPLETION SYNC END ==========\n")
            return {
                "success": True,
                "message": "Moodle completion update sent successfully."
            }

        print("✅ Moodle update sent successfully (course verification skipped).")
        print("========== MOODLE COMPLETION SYNC END ==========\n")
        return {
            "success": True,
            "message": "Moodle completion update sent successfully."
        }

    except Exception as e:
        print("❌ Moodle sync exception:", str(e))
        print("========== MOODLE COMPLETION SYNC END ==========\n")
        return {
            "success": False,
            "message": f"Moodle sync error: {str(e)}"
        }


def complete_module_and_try_moodle_sync(user, module):
    progress_obj = complete_module_for_user(user, module)
    moodle_sync = try_sync_module_completion_to_moodle(user, module)
    return progress_obj, moodle_sync
# =====================================
# HELPER: VIDEO WATCH VALIDATION
# =====================================
def get_or_create_video_watch_progress(user, module):
    return VideoWatchProgress.objects.get_or_create(
        student=user,
        module=module,
        defaults={
            "total_duration": 0,
            "watched_seconds": 0,
            "watched_percent": 0,
            "last_position": 0,
            "max_position_reached": 0,
            "heartbeat_count": 0,
            "is_completed": False,
        }
    )


def get_video_watch_progress(user, module):
    return VideoWatchProgress.objects.filter(
        student=user,
        module=module
    ).first()


def calculate_safe_watched_increment(progress_obj, event_type, current_time):
    """
    This prevents fake progress from large jumps.
    Only small forward movement is counted as real watch time.
    """
    if not progress_obj:
        return 0

    if event_type in ["seek"]:
        return 0

    if event_type in ["play", "pause"]:
        return 0

    previous_position = float(progress_obj.last_position or 0)
    current_time = float(current_time or 0)

    if current_time < previous_position:
        return 0

    difference = current_time - previous_position

    # Count only small realistic movement
    # If student jumps too much, do not count it
    if difference < 0:
        return 0

    if difference > 20:
        return 0

    return difference


def complete_video_module_after_validation(user, module):
    progress_obj, moodle_sync = complete_module_and_try_moodle_sync(user, module)
    return progress_obj, moodle_sync


def build_video_progress_payload(progress_obj):
    if not progress_obj:
        return {
            "watched_seconds": 0,
            "watched_percent": 0,
            "last_position": 0,
            "max_position_reached": 0,
            "heartbeat_count": 0,
            "is_completed": False,
        }

    return {
        "watched_seconds": round(float(progress_obj.watched_seconds or 0), 2),
        "watched_percent": round(float(progress_obj.watched_percent or 0), 2),
        "last_position": round(float(progress_obj.last_position or 0), 2),
        "max_position_reached": round(float(progress_obj.max_position_reached or 0), 2),
        "heartbeat_count": int(progress_obj.heartbeat_count or 0),
        "is_completed": bool(progress_obj.is_completed),
    }

# =====================================
# HELPER: QUIZ SCORING
# =====================================
def normalize_answer_text(value):
    return (value or "").strip().lower()


def build_quiz_result(module, post_data):
    questions = list(module.questions.all())
    total_questions = len(questions)
    correct_answers = 0

    for question in questions:
        selected_answer = (post_data.get(f"question_{question.id}") or "").strip()
        correct_answer = (question.answer or "").strip()

        question.selected_answer = selected_answer
        question.correct_answer = correct_answer
        question.is_correct = (
            normalize_answer_text(selected_answer) == normalize_answer_text(correct_answer)
            and selected_answer != ""
        )

        if question.is_correct:
            correct_answers += 1

    score_percent = 0
    if total_questions > 0:
        score_percent = int((correct_answers / total_questions) * 100)

    return {
        "questions": questions,
        "total_questions": total_questions,
        "correct_answers": correct_answers,
        "score_percent": score_percent,
    }


def save_quiz_attempt(user, module, quiz_result):
    return QuizAttempt.objects.create(
        student=user,
        module=module,
        total_questions=quiz_result["total_questions"],
        correct_answers=quiz_result["correct_answers"],
        score_percent=quiz_result["score_percent"],
    )


def get_latest_quiz_attempt(user, module):
    return QuizAttempt.objects.filter(
        student=user,
        module=module
    ).order_by("-submitted_at").first()


# =====================================
# HELPER: BUILD COURSE STATE FOR AJAX
# =====================================
def build_course_state_for_user(user, course):
    sections = get_course_sections(course)
    progress_data = get_course_progress_data(user, course, sections)
    completed_module_ids = progress_data["completed_module_ids"]
    locked_module_ids = get_locked_module_ids(user, course)
    next_unlocked_module_id = get_next_unlocked_module_id(user, course)

    modules_payload = []

    for section in sections:
        ordered_modules = list(
        section.modules.filter(is_published=True).order_by("order", "id")
    )

        for module in ordered_modules:
            latest_attempt = get_latest_quiz_attempt(user, module) if module.type == "quiz" else None

            # strict UI rule:
            # if module is locked by sequence, do not show it as completed/available
            is_locked = module.id in locked_module_ids
            is_completed = (module.id in completed_module_ids) and not is_locked

            modules_payload.append({
                "id": module.id,
                "section_id": section.id,
                "title": module.title,
                "type": module.type,
                "is_completed": is_completed,
                "is_locked": is_locked,
                "is_available": not is_locked,
                "is_current": module.id == next_unlocked_module_id,
                "latest_quiz_score": latest_attempt.score_percent if latest_attempt else None,
            })

    return {
        "total_modules": progress_data["total_modules"],
        "completed_modules": progress_data["completed_modules"],
        "pending_modules": progress_data["pending_modules"],
        "progress_percent": progress_data["progress_percent"],
        "next_unlocked_module_id": next_unlocked_module_id,
        "modules": modules_payload,
    }

# =====================================
# HELPER: DASHBOARD DATA
# =====================================
def get_completed_courses_count(user):
    count = 0

    for course in get_student_active_courses(user):
        sections = get_course_sections(course)
        progress_data = get_course_progress_data(user, course, sections)

        if progress_data["total_modules"] > 0 and progress_data["progress_percent"] == 100:
            count += 1

    return count


def get_total_pending_modules_count(user):
    total_pending = 0

    for course in get_student_active_courses(user):
        sections = get_course_sections(course)
        progress_data = get_course_progress_data(user, course, sections)
        total_pending += progress_data["pending_modules"]

    return total_pending


def get_total_certificates_count(user):
    return len(get_completed_courses_for_certificates(user))


def get_dashboard_continue_learning(user):
    for course in get_student_active_courses(user):
        sections = get_course_sections(course)
        progress_data = get_course_progress_data(user, course, sections)
        next_unlocked_module_id = get_next_unlocked_module_id(user, course)

        if next_unlocked_module_id:
            next_module = Module.objects.filter(
                id=next_unlocked_module_id
            ).select_related("section", "section__course").first()

            if next_module:
                route_name = None

                if next_module.type == "video":
                    route_name = "student:play_video"
                elif next_module.type == "theory":
                    route_name = "student:read_theory"
                elif next_module.type == "quiz":
                    route_name = "student:take_quiz"
                elif next_module.type == "material":
                    route_name = "student:material_page"

                return {
                    "course": course,
                    "module": next_module,
                    "progress_percent": progress_data["progress_percent"],
                    "route_name": route_name,
                }

    return None


def get_dashboard_recent_activity(user): 
    recent_progress = (
        StudentModuleProgress.objects.filter(
            student=user,
            is_completed=True
        )
        .select_related("module", "module__section", "module__section__course")
        .order_by("-completed_at")
        .first()
    )

    if recent_progress:
        return {
            "type": "module",
            "title": recent_progress.module.title,
            "course": recent_progress.module.section.course.title,
            "time": recent_progress.completed_at,
        }

    recent_quiz = (
        QuizAttempt.objects.filter(student=user)
        .select_related("module", "module__section", "module__section__course")
        .order_by("-submitted_at")
        .first()
    )

    if recent_quiz:
        return {
            "type": "quiz",
            "title": recent_quiz.module.title,
            "course": recent_quiz.module.section.course.title,
            "time": recent_quiz.submitted_at,
            "score_percent": recent_quiz.score_percent,
        }

    return None


def get_dashboard_course_cards(user):
    cards = []

    for course in get_student_active_courses(user)[:3]:
        sections = get_course_sections(course)
        progress_data = get_course_progress_data(user, course, sections)
        next_unlocked_module_id = get_next_unlocked_module_id(user, course)

        next_module = None
        if next_unlocked_module_id:
            next_module = Module.objects.filter(
                id=next_unlocked_module_id
            ).select_related("section").first()

        cards.append({
            "course": course,
            "progress_percent": progress_data["progress_percent"],
            "completed_modules": progress_data["completed_modules"],
            "total_modules": progress_data["total_modules"],
            "pending_modules": progress_data["pending_modules"],
            "next_module": next_module,
            "is_completed": progress_data["total_modules"] > 0 and progress_data["progress_percent"] == 100,
        })

    return cards
# =====================================
# HELPER: DASHBOARD DATA
# =====================================
def get_completed_courses_count(user):
    count = 0

    for course in get_student_active_courses(user):
        sections = get_course_sections(course)
        progress_data = get_course_progress_data(user, course, sections)

        if progress_data["total_modules"] > 0 and progress_data["progress_percent"] == 100:
            count += 1

    return count


def get_total_pending_modules_count(user):
    total_pending = 0

    for course in get_student_active_courses(user):
        sections = get_course_sections(course)
        progress_data = get_course_progress_data(user, course, sections)
        total_pending += progress_data["pending_modules"]

    return total_pending


def get_total_certificates_count(user):
    return len(get_completed_courses_for_certificates(user))


def get_dashboard_continue_learning(user):
    for course in get_student_active_courses(user):
        sections = get_course_sections(course)
        progress_data = get_course_progress_data(user, course, sections)
        next_unlocked_module_id = get_next_unlocked_module_id(user, course)

        if next_unlocked_module_id:
            next_module = Module.objects.filter(
                id=next_unlocked_module_id
            ).select_related("section", "section__course").first()

            if next_module:
                route_name = None

                if next_module.type == "video":
                    route_name = "student:play_video"
                elif next_module.type == "theory":
                    route_name = "student:read_theory"
                elif next_module.type == "quiz":
                    route_name = "student:take_quiz"
                elif next_module.type == "material":
                    route_name = "student:material_page"

                return {
                    "course": course,
                    "module": next_module,
                    "progress_percent": progress_data["progress_percent"],
                    "route_name": route_name,
                }

    return None

# =====================================
# DASHBOARD
# =====================================
@login_required
def student_dashboard(request):
    enrolled_courses = get_student_active_courses(request.user)

    enrolled_courses_count = len(enrolled_courses)
    completed_courses_count = get_completed_courses_count(request.user)
    pending_modules_count = get_total_pending_modules_count(request.user)
    certificates_count = get_total_certificates_count(request.user)

    continue_learning = get_dashboard_continue_learning(request.user)
    recent_activity = get_dashboard_recent_activity(request.user)
    course_cards = get_dashboard_course_cards(request.user)

    context = {
        "enrolled_courses_count": enrolled_courses_count,
        "completed_courses_count": completed_courses_count,
        "pending_modules_count": pending_modules_count,
        "certificates_count": certificates_count,
        "continue_learning": continue_learning,
        "recent_activity": recent_activity,
        "course_cards": course_cards,
    }
    return render(request, "student/student_dashboard.html", context)


def get_dashboard_recent_activity(user):
    recent_progress = (
        StudentModuleProgress.objects.filter(
            student=user,
            is_completed=True
        )
        .select_related("module", "module__section", "module__section__course")
        .order_by("-completed_at")
        .first()
    )

    if recent_progress:
        return {
            "type": "module",
            "title": recent_progress.module.title,
            "course": recent_progress.module.section.course.title,
            "time": recent_progress.completed_at,
        }

    recent_quiz = (
        QuizAttempt.objects.filter(student=user)
        .select_related("module", "module__section", "module__section__course")
        .order_by("-submitted_at")
        .first()
    )

    if recent_quiz:
        return {
            "type": "quiz",
            "title": recent_quiz.module.title,
            "course": recent_quiz.module.section.course.title,
            "time": recent_quiz.submitted_at,
            "score_percent": recent_quiz.score_percent,
        }

    return None


def get_dashboard_course_cards(user):
    cards = []

    for course in get_student_active_courses(user)[:3]:
        sections = get_course_sections(course)
        progress_data = get_course_progress_data(user, course, sections)
        next_unlocked_module_id = get_next_unlocked_module_id(user, course)

        next_module = None
        if next_unlocked_module_id:
            next_module = Module.objects.filter(
                id=next_unlocked_module_id
            ).select_related("section").first()

        cards.append({
            "course": course,
            "progress_percent": progress_data["progress_percent"],
            "completed_modules": progress_data["completed_modules"],
            "total_modules": progress_data["total_modules"],
            "pending_modules": progress_data["pending_modules"],
            "next_module": next_module,
            "is_completed": progress_data["total_modules"] > 0 and progress_data["progress_percent"] == 100,
        })

    return cards


# =====================================
# ENROLL COURSE
# =====================================
@login_required
def enroll_course(request, course_id):
    course = get_object_or_404(Course, id=course_id, is_published=True)

    existing_enrollment = Enrollment.objects.filter(
        student=request.user,
        course=course,
        is_active=True
    ).first()

    if existing_enrollment:
        messages.info(request, "You are already enrolled in this course.")
        return redirect("student:course_detail", course_id=course.id)

    user_profile = getattr(request.user, "profile", None)
    moodle_user_id = get_user_moodle_id(request.user)
    moodle_course_id = getattr(course, "moodle_course_id", None)

    if not user_profile:
        messages.error(request, "Student profile not found.")
        return redirect("student:my_courses")

    if not moodle_user_id:
        messages.error(request, "Your Moodle account is not linked yet. Please login again or contact admin.")
        return redirect("student:my_courses")

    if not moodle_course_id:
        messages.error(request, "This course is not synced with Moodle yet.")
        return redirect("student:my_courses")

    moodle_ok, moodle_error = enroll_student_to_course(
        moodle_user_id=moodle_user_id,
        moodle_course_id=moodle_course_id
    )

    if not moodle_ok:
        messages.error(request, f"Moodle enrollment failed: {moodle_error}")
        return redirect("student:my_courses")

    enrollment, created = Enrollment.objects.get_or_create(
        student=request.user,
        course=course,
        defaults={"is_active": True}
    )

    if not created and not enrollment.is_active:
        enrollment.is_active = True
        enrollment.save(update_fields=["is_active"])

    messages.success(request, "You have enrolled in this course successfully.")
    return redirect("student:course_detail", course_id=course.id)


# =====================================
# VIEW COURSE PREVIEW
# =====================================
@login_required
def view_course(request, course_id):
    course = get_object_or_404(Course, id=course_id, is_published=True)
    sections = get_course_sections(course)

    for section in sections:
        section.modules_list = list(
            section.modules.filter(is_published=True).order_by("order", "id")
        )

    already_enrolled = is_student_enrolled(request.user, course)

    context = {
        "course": course,
        "sections": sections,
        "already_enrolled": already_enrolled,
    }
    return render(request, "student/view_course.html", context)


# =====================================
# MY COURSES
# =====================================
@login_required
def my_courses(request):
    enrolled_courses = get_student_active_courses(request.user)

    available_courses = Course.objects.filter(
        is_published=True
    ).exclude(
        id__in=get_student_active_course_ids(request.user)
    ).order_by("-created_at")

    enrollments = Enrollment.objects.filter(
        student=request.user,
        is_active=True,
        course__is_published=True
    ).select_related("course").order_by("-enrolled_at")

    context = {
        "courses": enrolled_courses,
        "available_courses": available_courses,
        "enrollments": enrollments,
    }
    return render(request, "student/my_courses.html", context)


# =====================================
# PROGRESS
# =====================================
@login_required
def progress_tracker(request):
    courses = get_student_active_courses(request.user)
    progress_rows = []

    for course in courses:
        sections = get_course_sections(course)
        progress_data = get_course_progress_data(request.user, course, sections)

        progress_rows.append({
            "course": course,
            "total_modules": progress_data["total_modules"],
            "completed_modules": progress_data["completed_modules"],
            "pending_modules": progress_data["pending_modules"],
            "progress_percent": progress_data["progress_percent"],
        })

    context = {
        "progress_rows": progress_rows
    }
    return render(request, "student/progress.html", context)


# =====================================
# CERTIFICATES
# =====================================
@login_required
def certificates(request):
    certificate_rows = get_completed_courses_for_certificates(request.user)

    context = {
        "certificate_rows": certificate_rows
    }
    return render(request, "student/certificates.html", context)


@login_required
def download_certificate(request, course_id):
    course = get_object_or_404(Course, id=course_id, is_published=True)

    if not is_student_enrolled(request.user, course):
        messages.error(request, "You are not enrolled in this course.")
        return redirect("student:my_courses")

    if not is_course_completed_by_student(request.user, course):
        messages.warning(request, "You can download the certificate only after completing the full course.")
        return redirect("student:certificates")

    certificate_obj = get_or_create_student_certificate(
        request=request,
        user=request.user,
        course=course,
    )

    moodle_certificate_sync = try_issue_certificate_record_to_moodle(
        request=request,
        user=request.user,
        course=course,
        certificate_obj=certificate_obj,
    )

    if not moodle_certificate_sync["success"]:
        print("⚠️ Moodle certificate record sync failed:", moodle_certificate_sync["message"])
    else:
        print("✅ Moodle certificate record sync success:", moodle_certificate_sync["message"])

    safe_course_name = "".join(
        ch if ch.isalnum() or ch in (" ", "_", "-") else "_"
        for ch in course.title
    ).strip().replace(" ", "_")

    filename = f"{safe_course_name}_certificate.pdf"

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    draw_certificate_pdf(response, request.user, course, request=request)
    return response

# =====================================
# COURSE DETAIL
# =====================================
@login_required
def course_detail(request, course_id):
    course = get_object_or_404(Course, id=course_id, is_published=True)

    enrollment = get_active_enrollment(request.user, course)
    if not enrollment:
        messages.warning(request, "Please enroll in this course first.")
        return redirect("student:my_courses")

    sections = get_course_sections(course)

    progress_data = get_course_progress_data(request.user, course, sections)
    completed_module_ids = progress_data["completed_module_ids"]
    locked_module_ids = get_locked_module_ids(request.user, course)
    next_unlocked_module_id = get_next_unlocked_module_id(request.user, course)

    for section in sections:
        ordered_modules = list(section.modules.all().order_by("order", "id"))

        for module in ordered_modules:
            module.is_completed = module.id in completed_module_ids
            module.is_locked = module.id in locked_module_ids
            module.is_available = not module.is_locked
            module.is_current = module.id == next_unlocked_module_id

            if module.type == "quiz":
                latest_attempt = get_latest_quiz_attempt(request.user, module)
                module.latest_quiz_score = latest_attempt.score_percent if latest_attempt else None
            else:
                module.latest_quiz_score = None

        section.modules_list = ordered_modules

        if not hasattr(section, "_prefetched_objects_cache"):
            section._prefetched_objects_cache = {}
        section._prefetched_objects_cache["modules"] = ordered_modules

    context = {
        "course": course,
        "sections": sections,
        "enrollment": enrollment,
        "total_modules": progress_data["total_modules"],
        "completed_modules": progress_data["completed_modules"],
        "pending_modules": progress_data["pending_modules"],
        "progress_percent": progress_data["progress_percent"],
        "next_unlocked_module_id": next_unlocked_module_id,
        "is_certificate_available": progress_data["total_modules"] > 0 and progress_data["progress_percent"] == 100,
    }
    return render(request, "student/course_detail.html", context)


# =====================================
# PLAY VIDEO
# =====================================
@login_required
def play_video(request, module_id):
    module = get_object_or_404(Module, id=module_id, type="video")

    if not ensure_module_access(request, module):
        return redirect("student:course_detail", course_id=module.section.course.id)

    mpd_url = None
    if module.video_mpd:
        mpd_url = build_signed_stream_url(
            request=request,
            path=str(module.video_mpd).replace(os.sep, "/"),
            user_id=request.user.id
        )

    is_completed = StudentModuleProgress.objects.filter(
        student=request.user,
        module=module,
        is_completed=True
    ).exists()

    watch_progress, _ = get_or_create_video_watch_progress(request.user, module)

    context = {
        "module": module,
        "course": module.section.course,
        "section": module.section,
        "mpd_url": mpd_url,
        "is_completed": is_completed,
        "video_watch_progress": watch_progress,
        "watched_percent": round(float(watch_progress.watched_percent or 0), 2),
        "watched_seconds": round(float(watch_progress.watched_seconds or 0), 2),
        "required_watch_percent": 90,
        "heartbeat_url": f"/student/video-heartbeat/{module.id}/",
    }
    return render(request, "student/play_video.html", context)

# =====================================
# VIDEO HEARTBEAT API
# =====================================
@login_required
@require_POST
def save_video_heartbeat(request, module_id):
    module = get_object_or_404(Module, id=module_id, type="video")
    course = module.section.course

    if not ensure_module_access(request, module):
        return JsonResponse({
            "success": False,
            "error": "This module is locked or you are not enrolled in this course."
        }, status=403)

    try:
        event_type = (request.POST.get("event_type") or "heartbeat").strip().lower()
        current_time = float(request.POST.get("current_time") or 0)
        duration = float(request.POST.get("duration") or 0)
    except Exception:
        return JsonResponse({
            "success": False,
            "error": "Invalid heartbeat data."
        }, status=400)

    if event_type not in ["play", "pause", "heartbeat", "seek", "ended"]:
        event_type = "heartbeat"

    progress_obj, _ = get_or_create_video_watch_progress(request.user, module)

    increment_seconds = calculate_safe_watched_increment(
        progress_obj=progress_obj,
        event_type=event_type,
        current_time=current_time
    )

    VideoWatchEvent.objects.create(
        student=request.user,
        module=module,
        event_type=event_type,
        current_time=current_time,
        duration=duration,
    )

    progress_obj.update_progress(
        current_time=current_time,
        duration=duration,
        increment_seconds=increment_seconds
    )

    moodle_sync = None
    django_progress = StudentModuleProgress.objects.filter(
        student=request.user,
        module=module,
        is_completed=True
    ).first()

    if progress_obj.is_completed and not django_progress:
        _, moodle_sync = complete_video_module_after_validation(request.user, module)

    state = build_course_state_for_user(request.user, course)

    return JsonResponse({
        "success": True,
        "message": "Heartbeat saved successfully.",
        "event_type": event_type,
        "increment_seconds": round(float(increment_seconds or 0), 2),
        "video_progress": build_video_progress_payload(progress_obj),
        "completed_module_id": module.id if progress_obj.is_completed else None,
        "course_state": state,
        "moodle_sync": moodle_sync,
    })


# =====================================
# READ THEORY
# =====================================
@login_required
def read_theory(request, module_id):
    module = get_object_or_404(Module, id=module_id, type="theory")

    if not ensure_module_access(request, module):
        return redirect("student:course_detail", course_id=module.section.course.id)

    is_completed = StudentModuleProgress.objects.filter(
        student=request.user,
        module=module,
        is_completed=True
    ).exists()

    context = {
        "module": module,
        "course": module.section.course,
        "section": module.section,
        "is_completed": is_completed,
    }
    return render(request, "student/read_theory.html", context)


# =====================================
# TAKE QUIZ
# =====================================
@login_required
def take_quiz(request, module_id):
    module = get_object_or_404(Module, id=module_id, type="quiz")

    if not ensure_module_access(request, module):
        return redirect("student:course_detail", course_id=module.section.course.id)

    questions = list(module.questions.all())

    if request.method == "POST":
        if not questions:
            messages.error(request, "No quiz questions are available for this module.")
            return redirect("student:course_detail", course_id=module.section.course.id)

        quiz_result = build_quiz_result(module, request.POST)

        save_quiz_attempt(request.user, module, quiz_result)
        _, moodle_sync = complete_module_and_try_moodle_sync(request.user, module)

        success_message = (
            f"Quiz submitted successfully. Your score is "
            f"{quiz_result['correct_answers']}/{quiz_result['total_questions']} "
            f"({quiz_result['score_percent']}%)."
        )

        if moodle_sync["success"]:
            messages.success(request, success_message + " Moodle completion synced successfully.")
        else:
            messages.warning(request, success_message + f" Moodle sync failed: {moodle_sync['message']}")

        context = {
            "module": module,
            "course": module.section.course,
            "section": module.section,
            "questions": quiz_result["questions"],
            "is_completed": True,
            "quiz_result": {
                "correct_answers": quiz_result["correct_answers"],
                "total_questions": quiz_result["total_questions"],
                "score_percent": quiz_result["score_percent"],
            },
            "latest_attempt": None,
        }
        return render(request, "student/take_quiz.html", context)

    is_completed = StudentModuleProgress.objects.filter(
        student=request.user,
        module=module,
        is_completed=True
    ).exists()

    latest_attempt = get_latest_quiz_attempt(request.user, module)

    for question in questions:
        question.selected_answer = None
        question.correct_answer = (question.answer or "").strip()
        question.is_correct = False

    context = {
        "module": module,
        "course": module.section.course,
        "section": module.section,
        "questions": questions,
        "is_completed": is_completed,
        "quiz_result": None,
        "latest_attempt": latest_attempt,
    }
    return render(request, "student/take_quiz.html", context)


# =====================================
# MATERIAL PAGE
# =====================================
@login_required
def material_page(request, module_id):
    module = get_object_or_404(Module, id=module_id, type="material")

    if not ensure_module_access(request, module):
        return redirect("student:course_detail", course_id=module.section.course.id)

    real_file_path = get_real_material_path(module.material_file)

    is_completed = StudentModuleProgress.objects.filter(
        student=request.user,
        module=module,
        is_completed=True
    ).exists()

    context = {
        "module": module,
        "course": module.section.course,
        "section": module.section,
        "material_file": f"/student/material-file/{module.id}/" if real_file_path else None,
        "is_completed": is_completed,
    }
    return render(request, "student/material.html", context)


# =====================================
# MARK MODULE AS COMPLETED
# =====================================
@login_required
def mark_module_complete(request, module_id):
    module = get_object_or_404(Module, id=module_id, is_published=True)
    course = module.section.course
    is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"

    if not ensure_module_access(request, module):
        if is_ajax:
            return JsonResponse({
                "success": False,
                "error": "This module is locked or you are not enrolled in this course."
            }, status=403)
        return redirect("student:course_detail", course_id=course.id)

    if module.type == "quiz":
        if is_ajax:
            return JsonResponse({
                "success": False,
                "redirect_url": f"/student/quiz/{module.id}/",
                "error": "Quiz modules must be completed from the quiz page."
            }, status=400)
        return redirect("student:take_quiz", module_id=module.id)

    if module.type == "video":
        video_progress = get_video_watch_progress(request.user, module)

        if not video_progress or not video_progress.is_completed:
            message = "Video module will complete only after minimum 90% verified watch."

            if is_ajax:
                return JsonResponse({
                    "success": False,
                    "error": message,
                    "video_progress": build_video_progress_payload(video_progress),
                }, status=400)

            messages.warning(request, message)
            return redirect("student:play_video", module_id=module.id)

        django_progress = StudentModuleProgress.objects.filter(
            student=request.user,
            module=module,
            is_completed=True
        ).first()

        if not django_progress:
            _, moodle_sync = complete_video_module_after_validation(request.user, module)
        else:
            moodle_sync = {
                "success": True,
                "message": "Video module already completed."
            }

        if is_ajax:
            state = build_course_state_for_user(request.user, course)
            current_module_data = next(
                (item for item in state["modules"] if item["id"] == module.id),
                None
            )

            return JsonResponse({
                "success": True,
                "message": "Video module already completed after server-side validation.",
                "completed_module_id": module.id,
                "current_module": current_module_data,
                "course_state": state,
                "moodle_sync": moodle_sync,
                "video_progress": build_video_progress_payload(video_progress),
            })

        messages.success(request, "Video module completed successfully.")
        return redirect("student:course_detail", course_id=course.id)

    _, moodle_sync = complete_module_and_try_moodle_sync(request.user, module)

    if is_ajax:
        state = build_course_state_for_user(request.user, course)
        current_module_data = next(
            (item for item in state["modules"] if item["id"] == module.id),
            None
        )

        response_message = "Module completed successfully."
        if not moodle_sync["success"]:
            response_message += f" Moodle sync failed: {moodle_sync['message']}"

        return JsonResponse({
            "success": True,
            "message": response_message,
            "completed_module_id": module.id,
            "current_module": current_module_data,
            "course_state": state,
            "moodle_sync": moodle_sync,
        })

    next_url = request.GET.get("next")

    if next_url:
        return redirect(next_url)

    if moodle_sync["success"]:
        messages.success(request, "Module completed successfully and Moodle sync worked.")
    else:
        messages.warning(request, f"Module completed in Django, but Moodle sync failed: {moodle_sync['message']}")

    return redirect("student:course_detail", course_id=course.id)

# =====================================
# SERVE MATERIAL FILE FROM LMS STORAGE
# =====================================
@login_required
def serve_material_file(request, module_id):
    module = get_object_or_404(Module, id=module_id, type="material")

    if not ensure_module_access(request, module):
        return redirect("student:course_detail", course_id=module.section.course.id)

    real_file_path = get_real_material_path(module.material_file)

    if not real_file_path:
        raise Http404("Material file not found.")

    return FileResponse(open(real_file_path, "rb"), as_attachment=False)

# =====================================
# PROFILE PAGE
# =====================================
@login_required
def profile_page(request):
    user = request.user

    if request.method == "POST":
        username = (request.POST.get("username") or "").strip()
        email = (request.POST.get("email") or "").strip()
        full_name = (request.POST.get("full_name") or "").strip()

        current_password = (request.POST.get("current_password") or "").strip()
        new_password = (request.POST.get("new_password") or "").strip()
        confirm_password = (request.POST.get("confirm_password") or "").strip()

        # ===============================
        # UPDATE BASIC PROFILE
        # ===============================
        if username:
            user.username = username

        if email:
            user.email = email

        if full_name:
            parts = full_name.split()
            user.first_name = parts[0]
            user.last_name = " ".join(parts[1:]) if len(parts) > 1 else ""

        # ===============================
        # PASSWORD CHANGE
        # ===============================
        if current_password or new_password or confirm_password:
            if not current_password or not new_password or not confirm_password:
                messages.error(request, "Fill all password fields.")
                return redirect("student:profile")

            if not user.check_password(current_password):
                messages.error(request, "Wrong current password.")
                return redirect("student:profile")

            if new_password != confirm_password:
                messages.error(request, "Passwords do not match.")
                return redirect("student:profile")

            user.set_password(new_password)
            user.save()

            # 🔥 Moodle sync
            moodle_ok, moodle_error = update_moodle_user_profile_from_django_user(
                user,
                password=new_password
            )

            if moodle_ok:
                messages.success(request, "Password updated in Django + Moodle.")
            else:
                messages.warning(request, f"Moodle sync failed: {moodle_error}")

            return redirect("accounts:login")

        # ===============================
        # SAVE PROFILE
        # ===============================
        user.save()

        # 🔥 Moodle sync
        moodle_ok, moodle_error = update_moodle_user_profile_from_django_user(user)

        if moodle_ok:
            messages.success(request, "Profile updated successfully.")
        else:
            messages.warning(request, f"Moodle sync failed: {moodle_error}")

        return redirect("student:profile")

    # ===============================
    # GET DATA FOR PAGE
    # ===============================
    enrolled_courses = get_student_active_courses(user)

    context = {
        "user": user,
        "enrolled_courses_count": len(enrolled_courses),
        "completed_courses_count": get_completed_courses_count(user),
        "pending_modules_count": get_total_pending_modules_count(user),
        "certificates_count": get_total_certificates_count(user),
    }

    return render(request, "student/profile.html", context)

# =====================================
# SAVE WEBCAM SNAPSHOT
# =====================================
@login_required
@require_POST
def save_webcam_snapshot(request, module_id):
    module = get_object_or_404(Module, id=module_id, type="video")

    if not ensure_module_access(request, module):
        return JsonResponse({
            "success": False,
            "error": "This module is locked or you are not enrolled in this course."
        }, status=403)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({
            "success": False,
            "error": "Invalid JSON data."
        }, status=400)

    image_data = data.get("image")
    current_time = float(data.get("current_time") or 0)

    if not image_data:
        return JsonResponse({
            "success": False,
            "error": "No image data received."
        }, status=400)

    if ";base64," not in image_data:
        return JsonResponse({
            "success": False,
            "error": "Invalid image format."
        }, status=400)

    try:
        format_part, imgstr = image_data.split(";base64,")
        ext = format_part.split("/")[-1]
        file_name = f"webcam_{request.user.id}_{module.id}_{int(time.time())}.{ext}"
        image_file = ContentFile(base64.b64decode(imgstr), name=file_name)

        snapshot = WebcamSnapshot.objects.create(
            student=request.user,
            module=module,
            image=image_file,
        )

        return JsonResponse({
            "success": True,
            "message": "Webcam snapshot saved successfully.",
            "snapshot_id": snapshot.id,
            "current_time": current_time,
        })

    except Exception as e:
        return JsonResponse({
            "success": False,
            "error": f"Could not save webcam snapshot: {str(e)}"
        }, status=500)


# =====================================
# LOG TAB SWITCH
# =====================================
@login_required
@require_POST
def log_tab_switch(request, module_id):
    module = get_object_or_404(Module, id=module_id, type="video")

    if not ensure_module_access(request, module):
        return JsonResponse({
            "success": False,
            "error": "This module is locked or you are not enrolled in this course."
        }, status=403)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({
            "success": False,
            "error": "Invalid JSON data."
        }, status=400)

    current_time = float(data.get("current_time") or 0)
    note = (data.get("note") or "Browser tab switch detected.").strip()

    try:
        tab_log = TabSwitchLog.objects.create(
            student=request.user,
            module=module,
            current_time=current_time,
            note=note,
        )

        return JsonResponse({
            "success": True,
            "message": "Tab switch logged successfully.",
            "log_id": tab_log.id,
        })

    except Exception as e:
        return JsonResponse({
            "success": False,
            "error": f"Could not save tab switch log: {str(e)}"
        }, status=500)