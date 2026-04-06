import os
import time
import hmac
import hashlib
import subprocess
import requests
import json
import re

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.http import FileResponse, HttpResponse
from django.contrib import messages
from django.views.decorators.clickjacking import xframe_options_exempt

from .models import Course, Section, Module, QuizQuestion
from .forms import CourseForm
from .moodle_api import (
    create_moodle_course,
    sync_django_category_with_moodle,
)

# ==========================================
# MOODLE API CONFIG
# ==========================================

MOODLE_URL = "http://127.0.0.1/moodle/webservice/rest/server.php"
MOODLE_TOKEN = "53a8b7519e7d735edc9b6423e84f2b54"

# CHANGE THESE TWO VALUES TO YOUR REAL MOODLE IDs
MOODLE_AUTO_ENROLL_USER_ID = 2
MOODLE_AUTO_ENROLL_ROLE_ID = 3

# ==========================================
# SECURE STREAMING CONFIG
# ==========================================

STREAM_TOKEN_TTL_SECONDS = 60 * 30  # 30 minutes


# ==========================================
# SECURE STREAMING HELPERS
# ==========================================

def normalize_stream_path(path):
    return str(path or "").replace("\\", "/").lstrip("/")


def get_stream_signing_secret():
    return settings.SECRET_KEY.encode("utf-8")


def get_stream_resource_key(path):
    normalized_path = normalize_stream_path(path)
    return os.path.dirname(normalized_path).replace("\\", "/")


def build_stream_signature_message(path, user_id, expires):
    resource_key = get_stream_resource_key(path)
    return f"{resource_key}|{user_id}|{expires}"


def generate_stream_token(path, user_id, expires):
    message = build_stream_signature_message(path, user_id, expires).encode("utf-8")
    return hmac.new(
        get_stream_signing_secret(),
        message,
        hashlib.sha256
    ).hexdigest()


def build_signed_stream_url(request, path, user_id=None, expires_in=STREAM_TOKEN_TTL_SECONDS):
    normalized_path = normalize_stream_path(path)
    user_id = user_id or getattr(request.user, "id", 0) or 0
    expires = int(time.time()) + int(expires_in)
    token = generate_stream_token(normalized_path, user_id, expires)
    return f"/stream/{normalized_path}?expires={expires}&token={token}"


def stream_token_is_valid(path, user_id, expires, token):
    if not path or expires is None or token is None:
        return False

    if user_id is None:
        return False

    try:
        expires = int(expires)
        user_id = int(user_id)
    except Exception:
        return False

    if expires < int(time.time()):
        return False

    expected_token = generate_stream_token(path, user_id, expires)
    return hmac.compare_digest(str(token), expected_token)


def get_stream_content_type(file_path):
    lower_path = file_path.lower()

    if lower_path.endswith(".mpd"):
        return "application/dash+xml"
    if lower_path.endswith(".m4s"):
        return "video/mp4"
    if lower_path.endswith(".pdf"):
        return "application/pdf"
    if lower_path.endswith(".doc"):
        return "application/msword"
    if lower_path.endswith(".docx"):
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if lower_path.endswith(".ppt"):
        return "application/vnd.ms-powerpoint"
    if lower_path.endswith(".pptx"):
        return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    if lower_path.endswith(".txt"):
        return "text/plain"

    return "application/octet-stream"

def inject_stream_token_into_mpd(mpd_text, expires, token):
    """
    Add expires/token into MPD segment references so dash.js requests
    .m4s/.mp4 files with valid signed query params too.
    """
    if not mpd_text or expires is None or token is None:
        return mpd_text

    def add_query(uri):
        lower_uri = str(uri).lower()

        if not (
            lower_uri.endswith(".m4s")
            or lower_uri.endswith(".mp4")
            or lower_uri.endswith(".m4a")
        ):
            return uri

        if "expires=" in uri and "token=" in uri:
            return uri

        joiner = "&" if "?" in uri else "?"
        return f"{uri}{joiner}expires={expires}&token={token}"

    # initialization="..."
    mpd_text = re.sub(
        r'(initialization=")([^"]+)(")',
        lambda m: f'{m.group(1)}{add_query(m.group(2))}{m.group(3)}',
        mpd_text
    )

    # media="..."
    mpd_text = re.sub(
        r'(media=")([^"]+)(")',
        lambda m: f'{m.group(1)}{add_query(m.group(2))}{m.group(3)}',
        mpd_text
    )

    # single-quote support if present
    mpd_text = re.sub(
        r"(initialization=')([^']+)(')",
        lambda m: f"{m.group(1)}{add_query(m.group(2))}{m.group(3)}",
        mpd_text
    )

    mpd_text = re.sub(
        r"(media=')([^']+)(')",
        lambda m: f"{m.group(1)}{add_query(m.group(2))}{m.group(3)}",
        mpd_text
    )

    # <BaseURL>...</BaseURL> support
    mpd_text = re.sub(
        r'(<BaseURL>)([^<]+)(</BaseURL>)',
        lambda m: f"{m.group(1)}{add_query(m.group(2))}{m.group(3)}",
        mpd_text
    )

    return mpd_text


def is_video_stream_request(path):
    lower_path = normalize_stream_path(path).lower()
    return lower_path.endswith(".mpd") or lower_path.endswith(".m4s")


def is_safe_storage_path(base_path, relative_path):
    absolute_base = os.path.abspath(base_path)
    absolute_file = os.path.abspath(os.path.join(base_path, relative_path))
    return absolute_file.startswith(absolute_base), absolute_file


def get_video_module_from_stream_path(path):
    normalized_path = normalize_stream_path(path)

    # Direct MPD path match
    direct_module = Module.objects.filter(
        type="video",
        video_mpd=normalized_path
    ).select_related("section", "section__course").first()

    if direct_module:
        return direct_module

    # Segment file match by folder
    directory = os.path.dirname(normalized_path).replace("\\", "/")
    if not directory:
        return None

    possible_mpd_path = f"{directory}/stream.mpd"
    return Module.objects.filter(
        type="video",
        video_mpd=possible_mpd_path
    ).select_related("section", "section__course").first()


def request_user_has_video_access(request, module):
    user = getattr(request, "user", None)

    if not user or not user.is_authenticated:
        return False

    if user.is_staff or user.is_superuser:
        return True

    try:
        from student.models import Enrollment
    except Exception:
        return False

    return Enrollment.objects.filter(
        student=user,
        course=module.section.course,
        is_active=True
    ).exists()


def request_user_can_access_stream(request, path):
    """
    Rules:
    - Staff / superuser logged into Django: allowed directly
    - Non-video files: allowed directly
    - Video files:
        * logged-in student/teacher -> valid token + access check
        * Moodle iframe / signed public request -> valid token for user_id=0
    """
    user = getattr(request, "user", None)

    if user and user.is_authenticated and (user.is_staff or user.is_superuser):
        return True, None, "Staff access allowed."

    if not is_video_stream_request(path):
        return True, None, "Non-video file allowed."

    module = get_video_module_from_stream_path(path)

    if not module:
        return False, None, "Video module mapping not found."

    expires = request.GET.get("expires")
    token = request.GET.get("token")

    # Logged-in Django user flow
    if user and user.is_authenticated:
        if not stream_token_is_valid(path, user.id, expires, token):
            return False, module, "Invalid or expired stream token."

        if not request_user_has_video_access(request, module):
            return False, module, "You do not have access to this video."

        return True, module, "Access granted."

    # Moodle iframe / unsigned Django session but signed URL present
    if stream_token_is_valid(path, 0, expires, token):
        return True, module, "Signed iframe access allowed."

    return False, module, "Login required or invalid stream token."

# ==========================================
# MOODLE API FUNCTIONS
# ==========================================

def create_course_in_moodle(course):
    """
    Safe wrapper:
    - validates or repairs Moodle category mapping
    - creates course in Moodle using the safe helper from moodle_api.py
    """
    resolved_category_id, category_error = sync_django_category_with_moodle(course.category)

    if category_error:
        return {
            "success": False,
            "error": f"Category sync failed: {category_error}"
        }

    result_course_id, error = create_moodle_course(
        course_name=course.title,
        short_name=course.short_name,
        category_id=resolved_category_id,
        summary=getattr(course, "description", "") or "",
        visible=1 if getattr(course, "is_published", True) else 0,
        sections=getattr(course, "number_of_sections", 10) or 10,
        category_name=course.category.name,
        category_parent_id=None,
    )

    if error:
        return {
            "success": False,
            "error": error
        }

    return [{
        "id": result_course_id
    }]


def enroll_user_in_moodle_course(course_id, user_id, role_id):
    data = {
        "wstoken": MOODLE_TOKEN,
        "wsfunction": "enrol_manual_enrol_users",
        "moodlewsrestformat": "json",
        "enrolments[0][roleid]": role_id,
        "enrolments[0][userid]": user_id,
        "enrolments[0][courseid]": course_id,
    }

    response = requests.post(MOODLE_URL, data=data)

    print("Enroll status code:", response.status_code)
    print("Enroll raw response:", response.text[:500])

    try:
        json_data = response.json()
        print("👤 Enroll:", json_data)
        return json_data
    except Exception:
        if response.text.strip() == "":
            return {"status": "success"}

        return {
            "success": False,
            "error": response.text[:500]
        }


def update_section_in_moodle(course_id, section_id, name):
    data = {
        "wstoken": MOODLE_TOKEN,
        "wsfunction": "local_djangoapi_update_section",
        "moodlewsrestformat": "json",
        "courseid": course_id,
        "sectionid": section_id,
        "name": name,
    }

    response = requests.post(MOODLE_URL, data=data)

    print("Section update status code:", response.status_code)
    print("Section update raw response:", response.text[:500])

    try:
        json_data = response.json()
        print("✏️ Section Update:", json_data)
        return json_data
    except Exception:
        print("Section update response is not JSON")
        return {
            "success": False,
            "error": response.text[:500]
        }


def send_thumbnail_to_moodle(course_id, image_url):
    data = {
        "wstoken": MOODLE_TOKEN,
        "wsfunction": "local_djangoapi_upload_thumbnail",
        "moodlewsrestformat": "json",
        "courseid": course_id,
        "imageurl": image_url,
    }

    response = requests.post(MOODLE_URL, data=data)

    print("Thumbnail status code:", response.status_code)
    print("Thumbnail raw response:", response.text[:500])

    try:
        json_data = response.json()
        print("🖼 Thumbnail:", json_data)
        return json_data
    except Exception:
        print("Thumbnail response is not JSON")
        return {
            "success": False,
            "error": response.text[:500]
        }


def get_default_completion_payload():
    """
    Default completion settings for non-video modules.
    These modules can still use view-based completion if needed.
    """
    return {
        "completion": 2,
        "completionview": 1,
    }


def get_video_completion_payload():
    """
    Video completion must be controlled by Django after 90% watch.
    So Moodle should NOT auto-complete on activity view.
    """
    return {
        "completion": 2,
        "completionview": 0,
    }


def send_module_to_moodle(course_id, section_number, title, player_url):
    try:
        data = {
            "wstoken": MOODLE_TOKEN,
            "wsfunction": "local_djangoapi_create_module",
            "moodlewsrestformat": "json",
            "courseid": course_id,
            "sectionnumber": section_number,
            "name": title,
            "video_url": player_url,
        }

        data.update(get_video_completion_payload())

        response = requests.post(MOODLE_URL, data=data)

        print("Module status code:", response.status_code)
        print("Module payload:", data)
        print("Module raw response:", response.text[:500])

        try:
            json_data = response.json()
            print("🎯 Module:", json_data)
            return json_data
        except Exception:
            print("Module response is not JSON")
            return {
                "success": False,
                "error": response.text[:500]
            }

    except Exception as e:
        print("❌ Moodle API Error:", str(e))
        return {
            "success": False,
            "error": str(e)
        }


def send_theory_to_moodle(course_id, section_number, title, content):
    try:
        data = {
            "wstoken": MOODLE_TOKEN,
            "wsfunction": "local_djangoapi_create_theory",
            "moodlewsrestformat": "json",
            "courseid": course_id,
            "sectionnumber": section_number,
            "name": title,
            "content": content,
            "contentformat": 1,
        }

        data.update(get_default_completion_payload())

        response = requests.post(MOODLE_URL, data=data)

        print("Theory status code:", response.status_code)
        print("Theory payload:", data)
        print("Theory raw response:", response.text[:500])

        try:
            json_data = response.json()
            print("📄 Theory:", json_data)
            return json_data
        except Exception:
            print("Theory response is not JSON")
            return {
                "success": False,
                "error": response.text[:500]
            }

    except Exception as e:
        print("❌ Theory Moodle API Error:", str(e))
        return {
            "success": False,
            "error": str(e)
        }


def send_quiz_to_moodle(course_id, section_number, title, quiz_rows):
    """
    Send one quiz title with multiple questions to Moodle as JSON.
    """
    try:
        cleaned_questions = []

        for row in quiz_rows:
            cleaned_questions.append({
                "question": str(row.get("question", "")).strip(),
                "quiz_type": str(row.get("quiz_type", "")).strip(),
                "options": str(row.get("options", "")).strip(),
                "answer": str(row.get("answer", "")).strip(),
            })

        data = {
            "wstoken": MOODLE_TOKEN,
            "wsfunction": "local_djangoapi_create_quiz",
            "moodlewsrestformat": "json",
            "courseid": course_id,
            "sectionnumber": section_number,
            "name": title,
            "questionsjson": json.dumps(cleaned_questions),
        }

        data.update(get_default_completion_payload())

        response = requests.post(MOODLE_URL, data=data)

        print("Quiz status code:", response.status_code)
        print("Quiz payload sent:", data)
        print("Quiz raw response:", response.text[:1000])

        try:
            json_data = response.json()
            print("📝 Quiz:", json_data)
            return json_data
        except Exception:
            print("Quiz response is not JSON")
            return {
                "success": False,
                "error": response.text[:1000]
            }

    except Exception as e:
        print("❌ Quiz Moodle API Error:", str(e))
        return {
            "success": False,
            "error": str(e)
        }


def send_material_to_moodle(course_id, section_number, title, file_url, filename=""):
    try:
        data = {
            "wstoken": MOODLE_TOKEN,
            "wsfunction": "local_djangoapi_create_material",
            "moodlewsrestformat": "json",
            "courseid": course_id,
            "sectionnumber": section_number,
            "name": title,
            "file_url": file_url,
            "filename": filename,
        }

        data.update(get_default_completion_payload())

        response = requests.post(MOODLE_URL, data=data)

        print("Material status code:", response.status_code)
        print("Material payload:", data)
        print("Material raw response:", response.text[:500])

        try:
            json_data = response.json()
            print("📎 Material:", json_data)
            return json_data
        except Exception:
            print("Material response is not JSON")
            return {
                "success": False,
                "error": response.text[:500]
            }

    except Exception as e:
        print("❌ Material Moodle API Error:", str(e))
        return {
            "success": False,
            "error": str(e)
        }
    
def normalize_compare_text(value):
    return " ".join(str(value or "").strip().lower().split())


def fetch_moodle_course_contents(course_id):
    data = {
        "wstoken": MOODLE_TOKEN,
        "wsfunction": "core_course_get_contents",
        "moodlewsrestformat": "json",
        "courseid": course_id,
    }

    response = requests.post(MOODLE_URL, data=data)

    print("Recover mapping status code:", response.status_code)
    print("Recover mapping raw response:", response.text[:700])

    try:
        json_data = response.json()
        if isinstance(json_data, dict) and json_data.get("exception"):
            return None, json_data.get("message", "Moodle returned an exception.")
        return json_data, None
    except Exception:
        return None, response.text[:700]


def flatten_moodle_course_modules(course_contents):
    rows = []

    if not isinstance(course_contents, list):
        return rows

    for section in course_contents:
        section_number = section.get("section")
        modules = section.get("modules") or []

        for item in modules:
            rows.append({
                "section_number": section_number,
                "cmid": item.get("id"),
                "instanceid": item.get("instance"),
                "modname": item.get("modname"),
                "name": item.get("name"),
            })

    return rows


def recover_moodle_module_mapping(module):
    """
    Best-effort recovery for old modules where moodle_cmid was not saved.
    Match by:
    - Moodle course id
    - section number
    - module title
    """
    if not module:
        return False, "Module is missing."

    moodle_course_id = getattr(module.section.course, "moodle_course_id", None)
    section_number = getattr(module.section, "moodle_section_number", None)
    module_title = normalize_compare_text(module.title)

    if not moodle_course_id:
        return False, "Moodle course id is missing."

    if section_number is None:
        return False, "Moodle section number is missing."

    course_contents, error = fetch_moodle_course_contents(moodle_course_id)
    if error:
        return False, f"Could not fetch Moodle course contents: {error}"

    flat_rows = flatten_moodle_course_modules(course_contents)

    exact_matches = [
        row for row in flat_rows
        if row.get("section_number") == section_number
        and normalize_compare_text(row.get("name")) == module_title
    ]

    if not exact_matches:
        return False, "No matching Moodle activity found for this module."

    matched = exact_matches[-1]

    recovered_result = {
        "cmid": matched.get("cmid"),
        "instanceid": matched.get("instanceid"),
    }

    save_moodle_module_mapping(module, recovered_result)

    if module.moodle_cmid:
        print(
            f"✅ Recovered Moodle mapping for module {module.id}: "
            f"cmid={module.moodle_cmid}, instanceid={module.moodle_instance_id}"
        )
        return True, "Moodle module mapping recovered successfully."

    return False, "Matched Moodle activity found, but cmid could not be saved."


def moodle_result_ok(result):
    if not isinstance(result, dict):
        return False

    if result.get("success") is True:
        return True

    if result.get("status") == "success":
        return True

    if result.get("cmid") or result.get("instanceid"):
        return True

    return False


def save_moodle_module_mapping(module, moodle_result):
    """
    Save Moodle ids returned from plugin/webservice into Django Module.
    Safe and flexible for different response formats.
    """
    if not isinstance(moodle_result, dict):
        return

    changed_fields = []

    moodle_cmid = (
        moodle_result.get("cmid")
        or moodle_result.get("coursemodule")
        or moodle_result.get("coursemoduleid")
    )

    moodle_instance_id = (
        moodle_result.get("instanceid")
        or moodle_result.get("instance")
        or moodle_result.get("id")
    )

    moodle_module_id = (
        moodle_result.get("moduleid")
        or moodle_result.get("modid")
    )

    if moodle_cmid and module.moodle_cmid != moodle_cmid:
        module.moodle_cmid = moodle_cmid
        changed_fields.append("moodle_cmid")

    if moodle_instance_id and module.moodle_instance_id != moodle_instance_id:
        module.moodle_instance_id = moodle_instance_id
        changed_fields.append("moodle_instance_id")

    if moodle_module_id and module.moodle_module_id != moodle_module_id:
        module.moodle_module_id = moodle_module_id
        changed_fields.append("moodle_module_id")

    if changed_fields:
        module.save(update_fields=changed_fields)
        print(
            f"✅ Moodle mapping saved for module {module.id}: "
            f"cmid={module.moodle_cmid}, "
            f"instanceid={module.moodle_instance_id}, "
            f"moduleid={module.moodle_module_id}"
        )


def normalize_quiz_rows(request):
    questions = request.POST.getlist("quiz_question")
    quiz_types = request.POST.getlist("quiz_type")
    options_list = request.POST.getlist("quiz_options")
    answers = request.POST.getlist("quiz_answer")

    if not questions:
        single_question = (request.POST.get("quiz_question") or "").strip()
        single_type = (request.POST.get("quiz_type") or "").strip()
        single_options = (request.POST.get("quiz_options") or "").strip()
        single_answer = (request.POST.get("quiz_answer") or "").strip()

        if single_question or single_answer:
            questions = [single_question]
            quiz_types = [single_type]
            options_list = [single_options]
            answers = [single_answer]

    max_len = max(
        len(questions),
        len(quiz_types),
        len(options_list),
        len(answers),
        0
    )

    rows = []

    for i in range(max_len):
        question = questions[i].strip() if i < len(questions) and questions[i] else ""
        quiz_type = quiz_types[i].strip() if i < len(quiz_types) and quiz_types[i] else "mcq"
        options = options_list[i].strip() if i < len(options_list) and options_list[i] else ""
        answer = answers[i].strip() if i < len(answers) and answers[i] else ""

        if not question:
            continue

        if quiz_type == "true_false" and not options:
            options = "True\nFalse"

        rows.append({
            "question": question,
            "quiz_type": quiz_type,
            "options": options,
            "answer": answer
        })

    return rows


# ==========================================
# TEACHER DASHBOARD
# ==========================================

@login_required
def teacher_dashboard(request):
    context = {
        "total_courses": Course.objects.count(),
        "total_sections": Section.objects.count(),
        "published_courses": Course.objects.filter(is_published=True).count(),
        "draft_courses": Course.objects.filter(is_published=False).count(),
        "active_students": 0,
        "security_alerts": 0,
    }
    return render(request, "teacher/dashboard.html", context)


# ==========================================
# COURSE LIST
# ==========================================

@login_required
def course_list(request):
    courses = Course.objects.all()
    return render(request, "teacher/course_list.html", {"courses": courses})


# ==========================================
# CREATE COURSE
# ==========================================

@login_required
def create_course(request):
    if request.method == "POST":
        course_form = CourseForm(request.POST, request.FILES)

        if course_form.is_valid():
            course = course_form.save(commit=False)
            selected_category = course.category

            if not selected_category:
                messages.error(request, "Please choose a category.")
                return render(request, "teacher/create_course.html", {"course_form": course_form})

            resolved_category_id, category_error = sync_django_category_with_moodle(selected_category)

            if category_error:
                messages.error(request, f"Category sync failed: {category_error}")
                return render(request, "teacher/create_course.html", {"course_form": course_form})

            course.save()

            for i in range(1, course.number_of_sections + 1):
                Section.objects.create(
                    course=course,
                    title=f"Section {i}",
                    order=i,
                    moodle_section_number=i
                )

            moodle_course = create_course_in_moodle(course)

            if isinstance(moodle_course, list) and moodle_course:
                moodle_id = moodle_course[0]["id"]

                course.moodle_course_id = moodle_id

                if course.category.moodle_category_id != resolved_category_id:
                    course.category.moodle_category_id = resolved_category_id
                    course.category.save(update_fields=["moodle_category_id"])

                course.save()

                enroll_result = enroll_user_in_moodle_course(
                    moodle_id,
                    MOODLE_AUTO_ENROLL_USER_ID,
                    MOODLE_AUTO_ENROLL_ROLE_ID
                )

                if enroll_result.get("success") is False and enroll_result.get("status") != "success":
                    messages.warning(
                        request,
                        f"Course created, but auto enrollment failed: {enroll_result.get('error', enroll_result)}"
                    )

                data = {
                    "wstoken": MOODLE_TOKEN,
                    "wsfunction": "core_course_get_contents",
                    "moodlewsrestformat": "json",
                    "courseid": moodle_id
                }

                response = requests.post(MOODLE_URL, data=data)

                try:
                    moodle_sections = response.json()
                except Exception:
                    messages.warning(request, f"Course created, but section mapping failed: {response.text[:300]}")
                    return redirect("teacher:course_detail", course_id=course.id)

                django_sections = Section.objects.filter(course=course).order_by("order")

                for m_sec in moodle_sections:
                    section_number = m_sec.get("section")

                    if section_number == 0:
                        continue

                    try:
                        django_section = django_sections.get(order=section_number)
                        django_section.moodle_section_id = m_sec.get("id")
                        django_section.moodle_section_number = section_number
                        django_section.save()
                    except Section.DoesNotExist:
                        pass

                print("🔥 Moodle section IDs mapped successfully")

                if course.image:
                    image_url = request.build_absolute_uri(course.image.url)
                    thumb_result = send_thumbnail_to_moodle(moodle_id, image_url)

                    if not thumb_result.get("success", False) and thumb_result.get("status") != "success":
                        messages.warning(
                            request,
                            f"Course created, but thumbnail upload failed: {thumb_result.get('error', 'Unknown error')}"
                        )

                messages.success(request, "Course created successfully.")
                return redirect("teacher:course_detail", course_id=course.id)

            course.delete()

            if isinstance(moodle_course, dict):
                messages.error(
                    request,
                    moodle_course.get("error", "Moodle course creation failed.")
                )
            else:
                messages.error(request, "Moodle course creation failed.")

            return render(request, "teacher/create_course.html", {"course_form": course_form})

    else:
        course_form = CourseForm()

    return render(request, "teacher/create_course.html", {"course_form": course_form})


# ==========================================
# UPDATE SECTION
# ==========================================

@login_required
def update_section(request, section_id):
    section = get_object_or_404(Section, id=section_id)

    if request.method == "POST":
        new_title = (request.POST.get("title") or "").strip()

        if not new_title:
            messages.error(request, "Section title is required.")
            return redirect("teacher:course_detail", course_id=section.course.id)

        section.title = new_title
        section.save()

        if section.course.moodle_course_id and section.moodle_section_id:
            result = update_section_in_moodle(
                section.course.moodle_course_id,
                section.moodle_section_id,
                new_title
            )

            if not result.get("success", False) and result.get("status") != "success":
                messages.warning(
                    request,
                    f"Section updated in Django, but Moodle response was not confirmed: {result.get('error', 'Unknown error')}"
                )
            else:
                messages.success(request, "Section updated successfully in Django and Moodle.")
        else:
            messages.success(request, "Section updated successfully in Django.")

        return redirect("teacher:course_detail", course_id=section.course.id)

    return redirect("teacher:course_detail", course_id=section.course.id)


# ==========================================
# COURSE DETAIL
# ==========================================

@login_required
def course_detail(request, course_id):
    course = get_object_or_404(Course, id=course_id)
    sections = course.sections.all().order_by("order")

    return render(
        request,
        "teacher/course_detail.html",
        {"course": course, "sections": sections}
    )


# ==========================================
# PLAY MODULE (DASH PLAYER PAGE)
# ==========================================

@xframe_options_exempt
def play_module(request, module_id):
    module = get_object_or_404(Module, id=module_id)

    secure_mpd_url = None
    if module.video_mpd:
        secure_mpd_url = build_signed_stream_url(
            request=request,
            path=module.video_mpd,
            user_id=getattr(request.user, "id", 0) or 0
        )

    return render(
        request,
        "teacher/play_module.html",
        {
            "module": module,
            "secure_mpd_url": secure_mpd_url,
        }
    )


# ==========================================
# MODULE BUILDER
# ==========================================

@login_required
def module_builder(request, section_id):
    section = get_object_or_404(Section, id=section_id)

    if request.method == "POST":
        content_type = request.POST.get("type")
        title = (request.POST.get("title") or "").strip()

        if not title:
            messages.error(request, "Title is required.")
            return redirect("teacher:module_builder", section_id=section.id)

        module = Module.objects.create(
            section=section,
            title=title,
            type=content_type
        )

        try:
            # VIDEO
            if content_type == "video":
                video = request.FILES.get("video")

                if not video:
                    module.delete()
                    messages.error(request, "Please choose a video file.")
                    return redirect("teacher:module_builder", section_id=section.id)

                course_name = section.course.title.replace(" ", "_")
                section_name = f"section_{section.id}"
                module_name = f"module_{module.id}"

                base_path = settings.LMS_STORAGE_PATH
                folder_path = os.path.join(base_path, course_name, section_name, module_name)
                os.makedirs(folder_path, exist_ok=True)

                original_mp4 = os.path.join(folder_path, "original.mp4")

                with open(original_mp4, "wb+") as f:
                    for chunk in video.chunks():
                        f.write(chunk)

                ffmpeg_path = "C:\\ffmpeg\\bin\\ffmpeg.exe"

                command = [
                    ffmpeg_path,
                    "-i", "original.mp4",
                    "-c:v", "libx264",
                    "-preset", "veryfast",
                    "-pix_fmt", "yuv420p",
                    "-c:a", "aac",
                    "-b:a", "128k",
                    "-f", "dash",
                    "stream.mpd"
                ]

                result = subprocess.run(command, cwd=folder_path, capture_output=True, text=True)

                if result.returncode != 0:
                    print("FFmpeg Error:", result.stderr)
                    module.delete()
                    messages.error(request, "Video conversion failed.")
                    return redirect("teacher:module_builder", section_id=section.id)

                mpd_path = os.path.join(folder_path, "stream.mpd")

                if not os.path.exists(mpd_path):
                    module.delete()
                    messages.error(request, "MPD file was not created.")
                    return redirect("teacher:module_builder", section_id=section.id)

                module.video_mpd = os.path.join(course_name, section_name, module_name, "stream.mpd").replace("\\", "/")
                module.save()

                player_url = request.build_absolute_uri(f"/play-module/{module.id}/")

                moodle_result = {"success": True}

                if section.course.moodle_course_id and section.moodle_section_number is not None:
                    moodle_result = send_module_to_moodle(
                        section.course.moodle_course_id,
                        section.moodle_section_number,
                        module.title,
                        player_url
                    )
                    save_moodle_module_mapping(module, moodle_result)

                if moodle_result_ok(moodle_result) and not module.moodle_cmid:
                    recover_ok, recover_message = recover_moodle_module_mapping(module)
                    print("Video module recover mapping:", recover_ok, recover_message)

                if moodle_result_ok(moodle_result):
                    messages.success(request, "Video uploaded successfully in Django and Moodle.")
                else:
                    messages.warning(
                        request,
                        f"Video saved in Django, but Moodle failed: {moodle_result.get('error', moodle_result)}"
                    )

            # THEORY
            elif content_type == "theory":
                module.theory = request.POST.get("theory")
                module.save()

                moodle_result = {"success": True}

                if section.course.moodle_course_id and section.moodle_section_number is not None:
                    moodle_result = send_theory_to_moodle(
                        section.course.moodle_course_id,
                        section.moodle_section_number,
                        module.title,
                        module.theory
                    )
                    save_moodle_module_mapping(module, moodle_result)

                if moodle_result_ok(moodle_result):
                    messages.success(request, "Theory added successfully in Django and Moodle.")
                else:
                    messages.warning(
                        request,
                        f"Theory saved in Django, but Moodle failed: {moodle_result.get('error', moodle_result)}"
                    )

            # QUIZ
            elif content_type == "quiz":
                quiz_rows = normalize_quiz_rows(request)

                if not quiz_rows:
                    module.delete()
                    messages.error(request, "Please add at least one quiz question.")
                    return redirect("teacher:module_builder", section_id=section.id)

                for row in quiz_rows:
                    QuizQuestion.objects.create(
                        module=module,
                        question=row["question"],
                        quiz_type=row["quiz_type"],
                        options=row["options"],
                        answer=row["answer"]
                    )

                moodle_result = {"success": True}

                if section.course.moodle_course_id and section.moodle_section_number is not None:
                    moodle_result = send_quiz_to_moodle(
                        section.course.moodle_course_id,
                        section.moodle_section_number,
                        module.title,
                        quiz_rows
                    )
                    save_moodle_module_mapping(module, moodle_result)

                if moodle_result_ok(moodle_result):
                    messages.success(request, "Quiz added successfully in Django and Moodle.")
                else:
                    messages.warning(
                        request,
                        f"Quiz saved in Django, but Moodle failed: {moodle_result.get('error', moodle_result)}"
                    )

            # MATERIAL
            elif content_type == "material":
                material_file = request.FILES.get("material_file")

                if not material_file:
                    module.delete()
                    messages.error(request, "Please choose a material file.")
                    return redirect("teacher:module_builder", section_id=section.id)

                course_name = section.course.title.replace(" ", "_")
                section_name = f"section_{section.id}"
                module_name = f"module_{module.id}"

                base_path = settings.LMS_STORAGE_PATH
                folder_path = os.path.join(base_path, course_name, section_name, module_name)
                os.makedirs(folder_path, exist_ok=True)

                original_filename = material_file.name
                safe_filename = original_filename.replace(" ", "_")
                material_path = os.path.join(folder_path, safe_filename)

                with open(material_path, "wb+") as f:
                    for chunk in material_file.chunks():
                        f.write(chunk)

                relative_material_path = os.path.join(
                    course_name,
                    section_name,
                    module_name,
                    safe_filename
                ).replace("\\", "/")

                module.material_file = relative_material_path
                module.save()

                file_url = request.build_absolute_uri(f"/stream/{relative_material_path}")

                moodle_result = {"success": True}

                if section.course.moodle_course_id and section.moodle_section_number is not None:
                    moodle_result = send_material_to_moodle(
                        section.course.moodle_course_id,
                        section.moodle_section_number,
                        module.title,
                        file_url,
                        safe_filename
                    )
                    save_moodle_module_mapping(module, moodle_result)

                if moodle_result_ok(moodle_result):
                    messages.success(request, "Material added successfully in Django and Moodle.")
                else:
                    messages.warning(
                        request,
                        f"Material saved in Django, but Moodle failed: {moodle_result.get('error', moodle_result)}"
                    )

            else:
                module.delete()
                messages.error(request, "Invalid content type.")

        except Exception as e:
            print("ERROR:", str(e))
            module.delete()
            messages.error(request, f"Something went wrong: {str(e)}")

        return redirect("teacher:module_builder", section_id=section.id)

    modules = Module.objects.filter(section=section).order_by("-id").prefetch_related("questions")

    return render(
        request,
        "teacher/module_builder.html",
        {"section": section, "modules": modules}
    )


# ==========================================
# STREAM DASH FILES / MATERIAL FILES
# ==========================================

def serve_dash(request, path):
    normalized_path = normalize_stream_path(path)
    base_path = settings.LMS_STORAGE_PATH

    is_safe, file_path = is_safe_storage_path(base_path, normalized_path)
    if not is_safe:
        return HttpResponse("Invalid file path", status=403)

    if not os.path.exists(file_path):
        return HttpResponse("File not found", status=404)

    is_allowed, module, message = request_user_can_access_stream(request, normalized_path)
    if not is_allowed:
        print("❌ Stream denied:", message, "| path:", normalized_path)
        return HttpResponse(message, status=403)

    content_type = get_stream_content_type(file_path)

    # MPD file: rewrite segment URLs and attach signed token
    if normalized_path.lower().endswith(".mpd"):
        expires = request.GET.get("expires")
        token = request.GET.get("token")

        with open(file_path, "r", encoding="utf-8") as f:
            mpd_text = f.read()

        updated_mpd = inject_stream_token_into_mpd(
            mpd_text=mpd_text,
            expires=expires,
            token=token,
        )

        print(
            "✅ MPD served with signed segment URLs |",
            "path:", normalized_path,
            "| module:", getattr(module, "id", None),
            "| user:", getattr(getattr(request, "user", None), "username", None),
        )

        response = HttpResponse(updated_mpd, content_type="application/dash+xml")
        response["Cache-Control"] = "no-store"
        return response

    print(
        "✅ Stream allowed |",
        "path:", normalized_path,
        "| module:", getattr(module, "id", None),
        "| user:", getattr(getattr(request, "user", None), "username", None),
    )

    response = FileResponse(open(file_path, "rb"), content_type=content_type)
    response["Cache-Control"] = "no-store"
    return response