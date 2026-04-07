from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib import messages

from student.models import StudentCertificate
from teacher.models import Course
from teacher.moodle_api import (
    create_moodle_user,
    create_teacher_parent_category,
    create_default_child_categories,
)
from accounts.models import UserProfile, PendingTeacher
from .models import SystemSettings


def _is_admin(user):
    return user.is_authenticated and user.is_superuser


def _admin_required_redirect(request):
    if not _is_admin(request.user):
        messages.error(request, "Only admin can access this page.")
        return redirect('login')
    return None


def _get_user_role(user):
    if user.is_superuser:
        return 'Admin'
    elif user.is_staff:
        return 'Teacher'
    return 'Student'


def _get_user_full_name(user):
    full_name = user.get_full_name().strip()
    return full_name if full_name else user.username


def _get_moodle_user_id(user):
    profile = getattr(user, 'profile', None)
    if profile and profile.moodle_user_id:
        return profile.moodle_user_id
    return None


def _get_user_sync_status(user):
    return 'Synced' if _get_moodle_user_id(user) else 'Not Synced'


@login_required
def admin_dashboard(request):
    admin_check = _admin_required_redirect(request)
    if admin_check:
        return admin_check

    total_users = User.objects.count()
    total_students = User.objects.filter(is_staff=False, is_superuser=False).count()
    total_teachers = User.objects.filter(is_staff=True, is_superuser=False).count()
    total_admins = User.objects.filter(is_superuser=True).count()
    total_courses = Course.objects.count()
    pending_teacher_count = PendingTeacher.objects.count()

    recent_users_qs = User.objects.select_related('profile').all().order_by('-date_joined')[:5]
    recent_users = []
    for user in recent_users_qs:
        recent_users.append({
            'id': user.id,
            'username': user.username,
            'full_name': _get_user_full_name(user),
            'email': user.email,
            'role': _get_user_role(user),
            'is_active': user.is_active,
            'date_joined': user.date_joined,
            'moodle_user_id': _get_moodle_user_id(user),
            'sync_status': _get_user_sync_status(user),
        })

    context = {
        'total_users': total_users,
        'total_students': total_students,
        'total_teachers': total_teachers,
        'total_admins': total_admins,
        'total_courses': total_courses,
        'pending_teacher_count': pending_teacher_count,
        'recent_users': recent_users,
    }

    return render(request, 'adminpanel/dashboard.html', context)


@login_required
def user_management(request):
    admin_check = _admin_required_redirect(request)
    if admin_check:
        return admin_check

    users = User.objects.select_related('profile').all().order_by('-date_joined')

    user_list = []
    synced_users = 0
    unsynced_users = 0

    for user in users:
        moodle_user_id = _get_moodle_user_id(user)
        sync_status = 'Synced' if moodle_user_id else 'Not Synced'

        if moodle_user_id:
            synced_users += 1
        else:
            unsynced_users += 1

        user_list.append({
            'id': user.id,
            'username': user.username,
            'full_name': _get_user_full_name(user),
            'email': user.email,
            'role': _get_user_role(user),
            'is_active': user.is_active,
            'date_joined': user.date_joined,
            'approval_status': 'Approved',
            'moodle_user_id': moodle_user_id,
            'sync_status': sync_status,
        })

    pending_teachers_qs = PendingTeacher.objects.all().order_by('-created_at')

    pending_teachers = []
    for teacher in pending_teachers_qs:
        full_name = f"{teacher.first_name} {teacher.last_name}".strip()
        if not full_name:
            full_name = teacher.username

        pending_teachers.append({
            'id': teacher.id,
            'username': teacher.username,
            'full_name': full_name,
            'email': teacher.email,
            'date_joined': teacher.created_at,
            'sync_status': 'Pending Approval',
            'moodle_user_id': None,
        })

    context = {
        'users': user_list,
        'pending_teachers': pending_teachers,
        'total_users': len(user_list),
        'total_students': sum(1 for user in user_list if user['role'] == 'Student'),
        'total_teachers': sum(1 for user in user_list if user['role'] == 'Teacher'),
        'total_admins': sum(1 for user in user_list if user['role'] == 'Admin'),
        'pending_teacher_count': len(pending_teachers),
        'synced_users': synced_users,
        'unsynced_users': unsynced_users,
    }

    return render(request, 'adminpanel/users.html', context)


@login_required
def approve_teacher(request, user_id):
    admin_check = _admin_required_redirect(request)
    if admin_check:
        return admin_check

    pending_teacher = get_object_or_404(PendingTeacher, id=user_id)

    username = pending_teacher.username
    email = pending_teacher.email if pending_teacher.email else f"{username}@example.com"
    first_name = pending_teacher.first_name if pending_teacher.first_name else username
    last_name = pending_teacher.last_name if pending_teacher.last_name else "Teacher"
    raw_password = pending_teacher.password

    if User.objects.filter(username=username).exists():
        messages.error(request, f"A Django user with username '{username}' already exists.")
        return redirect('adminpanel:users')

    if User.objects.filter(email=email).exists():
        messages.error(request, f"A Django user with email '{email}' already exists.")
        return redirect('adminpanel:users')

    try:
        teacher_user = User.objects.create_user(
            username=username,
            email=email,
            password=raw_password,
            first_name=first_name,
            last_name=last_name,
        )
        teacher_user.is_staff = True
        teacher_user.is_active = True
        teacher_user.save(update_fields=['is_staff', 'is_active'])

        print("Django teacher user created:", teacher_user.username)

        moodle_user_id, moodle_error = create_moodle_user(
            username=username,
            password=raw_password,
            firstname=first_name,
            lastname=last_name,
            email=email
        )

        if not moodle_user_id:
            teacher_user.delete()
            messages.error(
                request,
                f"Moodle teacher creation failed: {moodle_error or 'Unknown error'}"
            )
            return redirect('adminpanel:users')

        print("Moodle teacher user created:", moodle_user_id)

        UserProfile.objects.update_or_create(
            user=teacher_user,
            defaults={
                'moodle_user_id': moodle_user_id,
            }
        )

        try:
            parent_category_id, category_error = create_teacher_parent_category(username)

            if parent_category_id:
                create_default_child_categories(parent_category_id)
                print("Teacher categories created successfully.")
            else:
                print("Teacher category creation failed:", category_error)

        except Exception as e:
            print("Teacher category creation error:", e)

        pending_teacher.delete()

        messages.success(
            request,
            f"Teacher '{teacher_user.username}' approved successfully. Django and Moodle users were created with the same password."
        )
        return redirect('adminpanel:users')

    except Exception as e:
        print("Teacher approval error:", e)
        messages.error(request, f"Teacher approval failed: {str(e)}")
        return redirect('adminpanel:users')


@login_required
def reject_teacher(request, user_id):
    admin_check = _admin_required_redirect(request)
    if admin_check:
        return admin_check

    pending_teacher = get_object_or_404(PendingTeacher, id=user_id)
    username = pending_teacher.username
    pending_teacher.delete()

    messages.success(request, f"Teacher request '{username}' rejected successfully.")
    return redirect('adminpanel:users')


@login_required
def audit_reports(request):
    admin_check = _admin_required_redirect(request)
    if admin_check:
        return admin_check

    total_users = User.objects.count()
    total_students = User.objects.filter(is_staff=False, is_superuser=False).count()
    total_teachers = User.objects.filter(is_staff=True, is_superuser=False).count()
    total_admins = User.objects.filter(is_superuser=True).count()
    total_courses = Course.objects.count()
    active_users = User.objects.filter(is_active=True).count()
    inactive_users = User.objects.filter(is_active=False).count()
    pending_teacher_count = PendingTeacher.objects.count()
    synced_users = UserProfile.objects.filter(moodle_user_id__isnull=False).exclude(moodle_user_id=0).count()
    unsynced_users = total_users - synced_users

    recent_users_qs = User.objects.select_related('profile').all().order_by('-date_joined')[:10]

    recent_users = []
    for user in recent_users_qs:
        recent_users.append({
            'username': user.username,
            'full_name': _get_user_full_name(user),
            'email': user.email,
            'role': _get_user_role(user),
            'is_active': user.is_active,
            'date_joined': user.date_joined,
            'moodle_user_id': _get_moodle_user_id(user),
            'sync_status': _get_user_sync_status(user),
        })

    context = {
        'total_users': total_users,
        'total_students': total_students,
        'total_teachers': total_teachers,
        'total_admins': total_admins,
        'total_courses': total_courses,
        'active_users': active_users,
        'inactive_users': inactive_users,
        'pending_teacher_count': pending_teacher_count,
        'synced_users': synced_users,
        'unsynced_users': unsynced_users,
        'recent_users': recent_users,
    }

    return render(request, 'adminpanel/reports.html', context)


@login_required
def course_management(request):
    admin_check = _admin_required_redirect(request)
    if admin_check:
        return admin_check

    courses = Course.objects.all().order_by('-id')

    course_list = []
    published_count = 0
    unpublished_count = 0
    synced_count = 0
    unsynced_count = 0

    for course in courses:
        is_published = getattr(course, 'is_published', False)
        moodle_course_id = getattr(course, 'moodle_course_id', None)

        if is_published:
            published_count += 1
        else:
            unpublished_count += 1

        if moodle_course_id:
            synced_count += 1
        else:
            unsynced_count += 1

        category_name = ''
        if hasattr(course, 'category') and course.category:
            category_name = course.category.name

        course_list.append({
            'id': course.id,
            'title': getattr(course, 'title', ''),
            'short_name': getattr(course, 'short_name', ''),
            'course_code': getattr(course, 'course_code', ''),
            'category_name': category_name,
            'description': getattr(course, 'description', ''),
            'is_published': is_published,
            'moodle_course_id': moodle_course_id,
            'sync_status': 'Synced' if moodle_course_id else 'Not Synced',
        })

    context = {
        'courses': course_list,
        'total_courses': len(course_list),
        'published_courses': published_count,
        'unpublished_courses': unpublished_count,
        'synced_courses': synced_count,
        'unsynced_courses': unsynced_count,
    }

    return render(request, 'adminpanel/courses.html', context)


@login_required
def certificate_control(request):
    admin_check = _admin_required_redirect(request)
    if admin_check:
        return admin_check

    certificates_qs = StudentCertificate.objects.select_related(
        'student',
        'course'
    ).order_by('-issued_at')

    certificate_list = []
    issued_count = 0
    pending_count = 0
    revoked_count = 0

    for cert in certificates_qs:
        if cert.status == 'issued':
            issued_count += 1
        elif cert.status == 'pending':
            pending_count += 1
        elif cert.status == 'revoked':
            revoked_count += 1

        student_name = cert.student.get_full_name().strip() if cert.student else ""
        if not student_name:
            student_name = cert.student.username if cert.student else "Unknown"

        course_title = cert.course.title if cert.course else "Unknown Course"

        certificate_list.append({
            'id': cert.id,
            'student_name': student_name,
            'course_title': course_title,
            'course_code': getattr(cert.course, 'course_code', ''),
            'certificate_code': cert.certificate_code,
            'moodle_certificate_id': cert.moodle_certificate_id,
            'verification_status': 'Synced' if cert.moodle_certificate_id else 'Not Synced',
            'status': cert.status.capitalize(),
            'issued_date': cert.issued_at,
        })

    context = {
        'certificates': certificate_list,
        'total_certificates': certificates_qs.count(),
        'issued_certificates': issued_count,
        'pending_certificates': pending_count,
        'revoked_certificates': revoked_count,
    }

    return render(request, 'adminpanel/certificates.html', context)


@login_required
def settings_compliance(request):
    admin_check = _admin_required_redirect(request)
    if admin_check:
        return admin_check

    settings_obj, _ = SystemSettings.objects.get_or_create(
        id=1,
        defaults={
            'video_host': 'http://127.0.0.1:8000',
            'token_expiry_seconds': 300,
            'certificate_signer': 'Authorized Signature',
            'signer_role': 'Instructor',
            'verification_label': 'Verify via LMS QR record',
            'qr_verification_enabled': True,
            'secure_streaming_enabled': True,
            'watch_validation_percent': 90,
            'quiz_completion_enabled': True,
            'moodle_base_url': 'http://127.0.0.1/moodle',
            'moodle_token': '',
            'moodle_admin_id': 2,
            'moodle_teacher_role': 3,
            'moodle_student_role': 5,
        }
    )

    if request.method == 'POST':
        settings_obj.video_host = request.POST.get('video_host', settings_obj.video_host).strip()
        settings_obj.certificate_signer = request.POST.get('certificate_signer', settings_obj.certificate_signer).strip()
        settings_obj.signer_role = request.POST.get('signer_role', settings_obj.signer_role).strip()
        settings_obj.verification_label = request.POST.get('verification_label', settings_obj.verification_label).strip()

        settings_obj.moodle_base_url = request.POST.get(
            'moodle_base_url',
            settings_obj.moodle_base_url
        ).strip()

        new_token = request.POST.get('moodle_token', '').strip()
        if new_token:
            settings_obj.moodle_token = new_token

        try:
            settings_obj.moodle_admin_id = int(
                request.POST.get('moodle_admin_id', settings_obj.moodle_admin_id)
            )
            settings_obj.moodle_teacher_role = int(
                request.POST.get('moodle_teacher_role', settings_obj.moodle_teacher_role)
            )
            settings_obj.moodle_student_role = int(
                request.POST.get('moodle_student_role', settings_obj.moodle_student_role)
            )
        except (TypeError, ValueError):
            messages.warning(request, "Moodle IDs must be valid numbers.")

        try:
            settings_obj.token_expiry_seconds = int(
                request.POST.get('token_expiry_seconds', settings_obj.token_expiry_seconds)
            )
        except (TypeError, ValueError):
            messages.warning(request, "Token expiry must be a valid number.")

        try:
            settings_obj.watch_validation_percent = int(
                request.POST.get('watch_validation_percent', settings_obj.watch_validation_percent)
            )
        except (TypeError, ValueError):
            messages.warning(request, "Watch validation percent must be a valid number.")

        settings_obj.qr_verification_enabled = request.POST.get('qr_verification_enabled') == 'on'
        settings_obj.secure_streaming_enabled = request.POST.get('secure_streaming_enabled') == 'on'
        settings_obj.quiz_completion_enabled = request.POST.get('quiz_completion_enabled') == 'on'

        settings_obj.save()
        messages.success(request, "System + Moodle settings updated successfully.")
        return redirect('adminpanel:settings')

    total_courses = Course.objects.count()
    synced_courses = Course.objects.filter(moodle_course_id__isnull=False).count()
    unsynced_courses = Course.objects.filter(moodle_course_id__isnull=True).count()
    published_courses = Course.objects.filter(is_published=True).count()
    unpublished_courses = Course.objects.filter(is_published=False).count()
    pending_teacher_count = PendingTeacher.objects.count()

    total_users = User.objects.count()
    synced_users = UserProfile.objects.filter(moodle_user_id__isnull=False).exclude(moodle_user_id=0).count()
    unsynced_users = total_users - synced_users

    system_settings = [
        {
            'title': 'Video Host',
            'value': settings_obj.video_host,
            'description': 'Streaming base URL used for secure video delivery.',
            'status': 'Active',
        },
        {
            'title': 'Token Expiry',
            'value': f'{settings_obj.token_expiry_seconds} Seconds',
            'description': 'Signed URL expiry time for secure streaming.',
            'status': 'Protected',
        },
        {
            'title': 'Certificate Signer',
            'value': settings_obj.certificate_signer,
            'description': f'Role: {settings_obj.signer_role}',
            'status': 'Active',
        },
        {
            'title': 'Moodle Base URL',
            'value': settings_obj.moodle_base_url,
            'description': 'Moodle web service endpoint base.',
            'status': 'Protected',
        },
        {
            'title': 'Moodle Token',
            'value': '********' if settings_obj.moodle_token else 'Not Set',
            'description': 'Hidden for security (used for API calls).',
            'status': 'Protected',
        },
        {
            'title': 'Moodle Roles',
            'value': f'Teacher: {settings_obj.moodle_teacher_role} | Student: {settings_obj.moodle_student_role}',
            'description': f'Admin ID: {settings_obj.moodle_admin_id}',
            'status': 'Protected',
        },
        {
            'title': 'Watch Rule',
            'value': f'{settings_obj.watch_validation_percent}%',
            'description': 'Minimum watch percentage required.',
            'status': 'Enforced',
        },
    ]

    compliance_checks = [
        {
            'name': 'Moodle Course Sync',
            'status': 'Good' if synced_courses > 0 else 'Pending',
            'detail': f'{synced_courses} synced / {unsynced_courses} pending',
        },
        {
            'name': 'Moodle User Sync',
            'status': 'Good' if synced_users > 0 else 'Pending',
            'detail': f'{synced_users} synced / {unsynced_users} pending',
        },
        {
            'name': 'Moodle Token Status',
            'status': 'Good' if settings_obj.moodle_token else 'Pending',
            'detail': 'Configured' if settings_obj.moodle_token else 'Token missing',
        },
        {
            'name': 'Teacher Approval Queue',
            'status': 'Good' if pending_teacher_count == 0 else 'Pending',
            'detail': f'{pending_teacher_count} pending',
        },
        {
            'name': 'Secure Learning Flow',
            'status': 'Enabled' if settings_obj.secure_streaming_enabled else 'Pending',
            'detail': 'Streaming protection active',
        },
    ]

    context = {
        'settings_obj': settings_obj,
        'total_courses': total_courses,
        'synced_courses': synced_courses,
        'unsynced_courses': unsynced_courses,
        'published_courses': published_courses,
        'unpublished_courses': unpublished_courses,
        'pending_teacher_count': pending_teacher_count,
        'total_users': total_users,
        'synced_users': synced_users,
        'unsynced_users': unsynced_users,
        'system_settings': system_settings,
        'compliance_checks': compliance_checks,
    }

    return render(request, 'adminpanel/settings.html', context)


@login_required
def revoke_certificate(request, cert_id):
    admin_check = _admin_required_redirect(request)
    if admin_check:
        return admin_check

    cert = get_object_or_404(StudentCertificate, id=cert_id)
    cert.status = 'revoked'
    cert.save(update_fields=['status'])

    messages.success(request, "Certificate revoked successfully.")
    return redirect('adminpanel:certificates')