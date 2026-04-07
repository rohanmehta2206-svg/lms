import os
import time
import html
import requests
from django.conf import settings


DEFAULT_TIMEOUT = 30


# ========================================
# DYNAMIC MOODLE CONFIGURATION
# ========================================

def get_system_settings_object():
    """
    Read Moodle configuration from adminpanel SystemSettings if available.
    Falls back safely to Django settings.py values.
    """
    try:
        from adminpanel.models import SystemSettings
        settings_obj = SystemSettings.objects.order_by("id").first()
        if settings_obj:
            return settings_obj
    except Exception as e:
        print("Could not load SystemSettings from DB:", e)

    return None


def get_moodle_base_url():
    settings_obj = get_system_settings_object()

    if settings_obj and getattr(settings_obj, "moodle_base_url", None):
        return str(settings_obj.moodle_base_url).rstrip("/")

    return getattr(settings, "MOODLE_BASE_URL", "http://127.0.0.1/moodle").rstrip("/")


def get_moodle_token():
    settings_obj = get_system_settings_object()

    if settings_obj and getattr(settings_obj, "moodle_token", None):
        return str(settings_obj.moodle_token).strip()

    return getattr(settings, "MOODLE_TOKEN", "53a8b7519e7d735edc9b6423e84f2b54")


def get_moodle_api_url():
    return f"{get_moodle_base_url()}/webservice/rest/server.php"


def get_moodle_upload_url():
    return f"{get_moodle_base_url()}/webservice/upload.php"


def get_moodle_admin_id():
    settings_obj = get_system_settings_object()

    if settings_obj and getattr(settings_obj, "moodle_admin_id", None):
        return int(settings_obj.moodle_admin_id)

    return int(getattr(settings, "MOODLE_ADMIN_ID", 2))


def get_moodle_teacher_role():
    settings_obj = get_system_settings_object()

    if settings_obj and getattr(settings_obj, "moodle_teacher_role", None):
        return int(settings_obj.moodle_teacher_role)

    return int(getattr(settings, "MOODLE_TEACHER_ROLE", 3))


def get_moodle_student_role():
    settings_obj = get_system_settings_object()

    if settings_obj and getattr(settings_obj, "moodle_student_role", None):
        return int(settings_obj.moodle_student_role)

    return int(getattr(settings, "MOODLE_STUDENT_ROLE", 5))


# ========================================
# GENERIC MOODLE API CALL
# ========================================

def call_moodle_api(function_name, params=None, timeout=DEFAULT_TIMEOUT):
    if params is None:
        params = {}

    moodle_token = get_moodle_token()
    moodle_api_url = get_moodle_api_url()

    payload = {
        "wstoken": moodle_token,
        "wsfunction": function_name,
        "moodlewsrestformat": "json",
    }
    payload.update(params)

    try:
        response = requests.post(
            moodle_api_url,
            data=payload,
            timeout=timeout
        )

        print("\n==============================")
        print("Function:", function_name)
        print("Payload:", payload)
        print("Status Code:", response.status_code)
        print("Response:", response.text)
        print("==============================\n")

        response.raise_for_status()
        data = response.json()

        if isinstance(data, dict) and data.get("exception"):
            return {
                "success": False,
                "error": data.get("message", "Unknown Moodle API exception"),
                "data": data
            }

        return {
            "success": True,
            "data": data
        }

    except requests.RequestException as e:
        print("Moodle API Request Error:", e)
        return {
            "success": False,
            "error": str(e)
        }
    except ValueError:
        print("Moodle API JSON Error: invalid JSON")
        return {
            "success": False,
            "error": "Invalid JSON response from Moodle"
        }
    except Exception as e:
        print("Moodle API Error:", e)
        return {
            "success": False,
            "error": str(e)
        }


# ========================================
# MOODLE CATEGORY HELPERS
# ========================================

def normalize_category_name(value):
    """
    Normalize category names so Moodle names like '&amp;' match Django names like '&'.
    """
    return html.unescape(str(value or "")).strip().lower()


def get_moodle_categories():
    result = call_moodle_api("core_course_get_categories", {})
    if result["success"] and isinstance(result["data"], list):
        return result["data"], None
    return [], result.get("error", "Could not fetch Moodle categories")


def get_moodle_category_by_id(category_id):
    if not category_id:
        return None, "No Moodle category id provided"

    categories, error = get_moodle_categories()
    if error:
        return None, error

    for category in categories:
        try:
            if int(category.get("id")) == int(category_id):
                return category, None
        except (TypeError, ValueError):
            continue

    return None, f"Moodle category id {category_id} not found"


def find_moodle_category_by_name(category_name, parent_id=None):
    if not category_name:
        return None, "No category name provided"

    categories, error = get_moodle_categories()
    if error:
        return None, error

    normalized_name = normalize_category_name(category_name)

    exact_matches = []
    for category in categories:
        moodle_name = normalize_category_name(category.get("name", ""))
        if moodle_name == normalized_name:
            exact_matches.append(category)

    if not exact_matches:
        return None, f"Moodle category '{category_name}' not found by name"

    if parent_id is not None:
        for category in exact_matches:
            try:
                if int(category.get("parent", 0)) == int(parent_id):
                    return category, None
            except (TypeError, ValueError):
                continue

        return None, f"Moodle category '{category_name}' not found under parent {parent_id}"

    return exact_matches[0], None


def ensure_moodle_category(category_id=None, category_name=None, parent_id=None):
    """
    Safe category resolver:
    1. Try existing category_id
    2. If invalid, try finding by name
    3. If still not found and category_name exists, create it
    """
    if category_id:
        category, error = get_moodle_category_by_id(category_id)
        if category:
            return category.get("id"), None
        print("Invalid Moodle category id:", category_id, "|", error)

    if category_name:
        category, error = find_moodle_category_by_name(category_name, parent_id=parent_id)
        if category:
            return category.get("id"), None

        print("Category not found by name:", category_name, "|", error)

        params = {
            "categories[0][name]": category_name,
            "categories[0][parent]": parent_id or 0
        }
        result = call_moodle_api("core_course_create_categories", params)

        if result["success"] and isinstance(result["data"], list) and result["data"]:
            new_id = result["data"][0].get("id")
            return new_id, None

        return None, result.get("error", f"Could not create Moodle category '{category_name}'")

    return None, "Could not resolve Moodle category"


def sync_django_category_with_moodle(django_category):
    """
    Repairs Django category mapping safely.
    """
    if django_category is None:
        return None, "Django category object is required"

    resolved_id, error = ensure_moodle_category(
        category_id=getattr(django_category, "moodle_category_id", None),
        category_name=getattr(django_category, "name", None),
        parent_id=None
    )

    if error:
        return None, error

    if getattr(django_category, "moodle_category_id", None) != resolved_id:
        django_category.moodle_category_id = resolved_id
        django_category.save(update_fields=["moodle_category_id"])

    return resolved_id, None


# ========================================
# CREATE MOODLE COURSE
# ========================================

def create_moodle_course(
    course_name,
    short_name,
    category_id,
    summary="",
    visible=1,
    sections=10,
    category_name=None,
    category_parent_id=None,
):
    resolved_category_id, category_error = ensure_moodle_category(
        category_id=category_id,
        category_name=category_name,
        parent_id=category_parent_id
    )

    if category_error:
        return None, f"Category validation failed: {category_error}"

    params = {
        "courses[0][fullname]": course_name,
        "courses[0][shortname]": short_name,
        "courses[0][categoryid]": resolved_category_id,
        "courses[0][summary]": summary,
        "courses[0][visible]": visible,
        "courses[0][numsections]": sections,
    }

    result = call_moodle_api("core_course_create_courses", params)

    if result["success"] and isinstance(result["data"], list) and result["data"]:
        return result["data"][0].get("id"), None

    moodle_error = result.get("error", "Course creation failed")
    return None, f"Course creation failed in Moodle: {moodle_error}"


# ========================================
# UPDATE MOODLE COURSE
# ========================================

def update_moodle_course(course_id, fullname=None, shortname=None, category_id=None, summary=None, visible=None):
    params = {
        "courses[0][id]": course_id,
    }

    if fullname is not None:
        params["courses[0][fullname]"] = fullname
    if shortname is not None:
        params["courses[0][shortname]"] = shortname
    if category_id is not None:
        params["courses[0][categoryid]"] = category_id
    if summary is not None:
        params["courses[0][summary]"] = summary
    if visible is not None:
        params["courses[0][visible]"] = int(visible)

    result = call_moodle_api("core_course_update_courses", params)

    if result["success"]:
        return True, None

    return False, result.get("error", "Course update failed")


# ========================================
# ENROLL USER INTO COURSE
# ========================================

def is_user_enrolled_in_moodle_course(user_id, course_id):
    if not user_id or not course_id:
        return False

    params = {
        "userid": user_id
    }

    result = call_moodle_api("core_enrol_get_users_courses", params)

    if not result["success"]:
        return False

    data = result.get("data", [])
    if not isinstance(data, list):
        return False

    for course in data:
        try:
            if int(course.get("id")) == int(course_id):
                return True
        except (TypeError, ValueError):
            continue

    return False


def enroll_user_to_course(user_id, course_id, role_id=None):
    if not user_id:
        return False, "Moodle user id is required"

    if not course_id:
        return False, "Moodle course id is required"

    if role_id is None:
        role_id = get_moodle_teacher_role()

    if is_user_enrolled_in_moodle_course(user_id, course_id):
        return True, None

    params = {
        "enrolments[0][roleid]": role_id,
        "enrolments[0][userid]": user_id,
        "enrolments[0][courseid]": course_id,
    }

    result = call_moodle_api("enrol_manual_enrol_users", params)

    if result["success"]:
        return True, None

    error_message = result.get("error", "Enrollment failed")

    if "Message was not sent" in str(error_message):
        if is_user_enrolled_in_moodle_course(user_id, course_id):
            print("Enrollment completed in Moodle, but message sending failed. Treating as success.")
            return True, None

    if is_user_enrolled_in_moodle_course(user_id, course_id):
        return True, None

    return False, error_message


def enroll_admin_to_course(course_id):
    return enroll_user_to_course(
        get_moodle_admin_id(),
        course_id,
        get_moodle_teacher_role()
    )


def enroll_student_to_course(moodle_user_id, moodle_course_id, role_id=None):
    """
    Enroll a real student into a real Moodle course.
    This should be called when a student clicks Enroll in Django.
    """
    if not moodle_user_id:
        return False, "Student Moodle user id is missing"

    if not moodle_course_id:
        return False, "Course Moodle course id is missing"

    if role_id is None:
        role_id = get_moodle_student_role()

    return enroll_user_to_course(
        user_id=moodle_user_id,
        course_id=moodle_course_id,
        role_id=role_id
    )


# ========================================
# MOODLE COMPLETION HELPERS
# ========================================

def get_course_completion_status(moodle_course_id, moodle_user_id):
    if not moodle_course_id:
        return False, "Moodle course id is required", None

    if not moodle_user_id:
        return False, "Moodle user id is required", None

    params = {
        "courseid": moodle_course_id,
        "userid": moodle_user_id,
    }

    result = call_moodle_api("core_completion_get_course_completion_status", params)

    if result["success"]:
        return True, None, result.get("data")

    return False, result.get("error", "Could not fetch Moodle course completion status"), None


def get_activities_completion_status(moodle_course_id, moodle_user_id):
    if not moodle_course_id:
        return False, "Moodle course id is required", None

    if not moodle_user_id:
        return False, "Moodle user id is required", None

    params = {
        "courseid": moodle_course_id,
        "userid": moodle_user_id,
    }

    result = call_moodle_api("core_completion_get_activities_completion_status", params)

    if result["success"]:
        return True, None, result.get("data")

    return False, result.get("error", "Could not fetch Moodle activities completion status"), None


def _is_missing_custom_completion_function(error_text):
    text = str(error_text or "").lower()
    markers = [
        "function does not exist",
        "access control exception",
        "can not find data record in database table external_functions",
        "servicenotavailable",
        "invalidparameter",
    ]
    return any(marker in text for marker in markers)


def mark_moodle_activity_complete(moodle_user_id, cmid):
    if not moodle_user_id:
        return False, "Moodle user id is required"

    if not cmid:
        return False, "Moodle cmid is required"

    custom_params = {
        "userid": moodle_user_id,
        "cmid": cmid,
        "completed": 1,
    }

    custom_result = call_moodle_api("local_djangoapi_mark_activity_complete", custom_params)

    if custom_result["success"]:
        return True, "Moodle activity marked as completed successfully"

    custom_error = custom_result.get("error", "Could not update Moodle activity completion")

    if not _is_missing_custom_completion_function(custom_error):
        return False, custom_error

    fallback_params = {
        "cmid": cmid,
        "completed": 1,
    }

    fallback_result = call_moodle_api("core_completion_update_activity_completion_status_manually", fallback_params)

    if fallback_result["success"]:
        return True, "Moodle activity marked as completed successfully"

    return False, fallback_result.get("error", "Could not update Moodle activity completion")


def mark_moodle_activity_incomplete(moodle_user_id, cmid):
    if not moodle_user_id:
        return False, "Moodle user id is required"

    if not cmid:
        return False, "Moodle cmid is required"

    custom_params = {
        "userid": moodle_user_id,
        "cmid": cmid,
        "completed": 0,
    }

    custom_result = call_moodle_api("local_djangoapi_mark_activity_complete", custom_params)

    if custom_result["success"]:
        return True, "Moodle activity marked as incomplete successfully"

    custom_error = custom_result.get("error", "Could not update Moodle activity completion")

    if not _is_missing_custom_completion_function(custom_error):
        return False, custom_error

    fallback_params = {
        "cmid": cmid,
        "completed": 0,
    }

    fallback_result = call_moodle_api("core_completion_update_activity_completion_status_manually", fallback_params)

    if fallback_result["success"]:
        return True, "Moodle activity marked as incomplete successfully"

    return False, fallback_result.get("error", "Could not update Moodle activity completion")


def get_single_activity_completion_state(moodle_course_id, moodle_user_id, cmid):
    ok, error, data = get_activities_completion_status(moodle_course_id, moodle_user_id)

    if not ok:
        return False, error, None

    statuses = []

    if isinstance(data, dict):
        statuses = data.get("statuses", [])
    elif isinstance(data, list):
        statuses = data

    for row in statuses:
        try:
            if int(row.get("cmid")) == int(cmid):
                return True, None, row
        except (TypeError, ValueError):
            continue

    return False, f"Completion row not found for cmid {cmid}", None


# ========================================
# ISSUE CERTIFICATE RECORD IN MOODLE
# ========================================

def issue_moodle_certificate_record(moodle_user_id, moodle_course_id, certificate_id, certificate_url="", issuedate=None):
    """
    Store certificate issue record in Moodle via custom local plugin function.
    Returns Moodle certificate record id (if available).
    """

    if not moodle_user_id:
        return False, "Moodle user id is required", None

    if not moodle_course_id:
        return False, "Moodle course id is required", None

    if not certificate_id:
        return False, "Certificate id is required", None

    if issuedate is None:
        issuedate = int(time.time())
    else:
        try:
            issuedate = int(issuedate)
        except (TypeError, ValueError):
            issuedate = int(time.time())

    params = {
        "userid": moodle_user_id,
        "courseid": moodle_course_id,
        "certificateid": str(certificate_id).strip(),
        "certificateurl": str(certificate_url or "").strip(),
        "issuedate": issuedate,
    }

    result = call_moodle_api("local_djangoapi_issue_certificate", params)

    if result["success"]:
        data = result.get("data")

        moodle_cert_id = None

        if isinstance(data, dict):
            moodle_cert_id = data.get("id") or data.get("certificateid")

        elif isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, dict):
                moodle_cert_id = first.get("id") or first.get("certificateid")

        return True, None, moodle_cert_id

    return False, result.get("error", "Could not store certificate issue record in Moodle"), None


# ========================================
# UPLOAD IMAGE TO MOODLE
# ========================================

def upload_course_image(image_path):
    try:
        if not os.path.exists(image_path):
            return None, f"Image file not found: {image_path}"

        moodle_upload_url = get_moodle_upload_url()
        moodle_token = get_moodle_token()

        with open(image_path, "rb") as f:
            response = requests.post(
                moodle_upload_url,
                params={
                    "token": moodle_token,
                    "filepath": "/",
                    "itemid": 0
                },
                files={"file": f},
                timeout=DEFAULT_TIMEOUT
            )

        response.raise_for_status()
        data = response.json()

        print("Upload Response:", data)

        if isinstance(data, list) and len(data) > 0:
            return data[0].get("itemid"), None

        return None, "Unexpected Moodle upload response"

    except Exception as e:
        print("Image Upload Error:", e)
        return None, str(e)


def attach_image_to_course(course_id, draft_item_id):
    params = {
        "courses[0][id]": course_id,
        "courses[0][overviewfiles][0][fileitemid]": draft_item_id
    }

    result = call_moodle_api("core_course_update_courses", params)

    if result["success"]:
        return True, None

    return False, result.get("error", "Image attach failed")


def upload_and_set_course_image(course_id, image_path):
    print("========== IMAGE UPLOAD START ==========")

    draft_id, error = upload_course_image(image_path)
    print("Draft ID:", draft_id)

    if error:
        print("Image Upload Error:", error)
        print("========== IMAGE UPLOAD END ==========")
        return False, error

    ok, error = attach_image_to_course(course_id, draft_id)
    print("========== IMAGE UPLOAD END ==========")

    if not ok:
        return False, error

    return True, None


# ========================================
# CREATE / UPDATE MOODLE SECTION
# ========================================

def create_or_update_moodle_section(course_id, section_number, section_name, summary=""):
    params = {
        "courseid": course_id,
        "sectionnumber": section_number,
        "name": section_name,
        "summary": summary
    }

    result = call_moodle_api("core_course_edit_section", params)

    if result["success"]:
        return True, None

    return False, result.get("error", "Section update failed")


def create_moodle_section(course_id, section_number, section_name):
    return create_or_update_moodle_section(course_id, section_number, section_name)


def update_moodle_section_name(course_id, section_number, section_name):
    return create_or_update_moodle_section(course_id, section_number, section_name)


def get_course_contents(course_id):
    params = {
        "courseid": course_id
    }

    result = call_moodle_api("core_course_get_contents", params)

    if result["success"]:
        return result["data"], None

    return None, result.get("error", "Could not fetch course contents")


def get_moodle_section_info(course_id, section_number):
    contents, error = get_course_contents(course_id)

    if error:
        return None, error

    if not isinstance(contents, list):
        return None, "Invalid course contents response"

    for section in contents:
        if section.get("section") == section_number:
            return {
                "id": section.get("id"),
                "section": section.get("section"),
                "name": section.get("name"),
            }, None

    return None, f"Section {section_number} not found in Moodle course {course_id}"


# ========================================
# CREATE MOODLE VIDEO PAGE IN SAME SECTION
# ========================================

def create_moodle_video_module(course_id, section_number, name, video_url):
    """
    Calls your custom Moodle plugin function.
    This creates a PAGE activity in the exact Moodle section number.
    """
    params = {
        "courseid": course_id,
        "sectionnumber": section_number,
        "name": name,
        "video_url": video_url,
    }

    result = call_moodle_api("local_djangoapi_create_module", params)

    if not result["success"]:
        return False, result.get("error", "Video module creation failed"), None

    data = result["data"]
    module_data = {
        "cmid": None,
        "sectionid": None,
        "sectionnumber": None,
    }

    if isinstance(data, dict):
        module_data["cmid"] = data.get("cmid")
        module_data["sectionid"] = data.get("sectionid")
        module_data["sectionnumber"] = data.get("sectionnumber")

    return True, None, module_data


# ========================================
# CREATE MOODLE THEORY PAGE
# ========================================

def create_moodle_theory_page(course_id, section_number, name, content):
    params = {
        "pages[0][courseid]": course_id,
        "pages[0][name]": name,
        "pages[0][content]": content,
        "pages[0][section]": section_number,
    }

    result = call_moodle_api("mod_page_create_pages", params)

    if not result["success"]:
        return False, result.get("error", "Theory page creation failed"), None

    data = result["data"]
    page_data = {
        "id": None,
        "cmid": None,
    }

    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            page_data["id"] = first.get("id")
            page_data["cmid"] = first.get("coursemodule") or first.get("cmid")

    return True, None, page_data


# ========================================
# THUMBNAIL VIA LOCAL MOODLE PLUGIN
# ========================================

def upload_thumbnail_via_plugin(course_id, image_url):
    params = {
        "courseid": course_id,
        "imageurl": image_url
    }

    result = call_moodle_api("local_djangoapi_upload_thumbnail", params)

    if result["success"]:
        return True, None

    return False, result.get("error", "Thumbnail upload failed")


# ========================================
# CREATE TEACHER PARENT CATEGORY
# ========================================

def create_teacher_parent_category(teacher_name):
    existing_category, _ = find_moodle_category_by_name(teacher_name, parent_id=0)
    if existing_category:
        return existing_category.get("id"), None

    params = {
        "categories[0][name]": teacher_name,
        "categories[0][parent]": 0
    }

    result = call_moodle_api("core_course_create_categories", params)

    if result["success"] and isinstance(result["data"], list) and result["data"]:
        return result["data"][0].get("id"), None

    return None, result.get("error", "Parent category creation failed")


# ========================================
# CREATE DEFAULT CHILD CATEGORIES
# ========================================

def create_default_child_categories(parent_id):
    from .models import Category

    default_categories = [
        "Programming Languages",
        "Web Development",
        "Mobile Development",
        "Game Development",
        "Data Science & AI",
        "IT & Software",
        "Cyber Security",
        "Cloud & DevOps",
        "UI/UX & Design",
        "Business & Freelancing",
        "Career Paths",
        "Tools & Technologies",
        "Other"
    ]

    created_items = []

    for position, category_name in enumerate(default_categories, start=1):
        moodle_id, error = ensure_moodle_category(
            category_id=None,
            category_name=category_name,
            parent_id=parent_id
        )

        if error:
            print(f"Could not create/sync category '{category_name}': {error}")
            continue

        category, _ = Category.objects.update_or_create(
            name=category_name,
            defaults={
                "position": position,
                "moodle_category_id": moodle_id
            }
        )
        created_items.append(category)

    return created_items


# ========================================
# CREATE MOODLE USER
# ========================================

def create_moodle_user(username, password, firstname, lastname, email):
    params = {
        "users[0][username]": username.strip(),
        "users[0][password]": password,
        "users[0][firstname]": firstname.strip(),
        "users[0][lastname]": lastname.strip(),
        "users[0][email]": email.strip(),
        "users[0][auth]": "manual",
        "users[0][lang]": "en",
        "users[0][timezone]": "Asia/Kolkata",
        "users[0][mailformat]": 1,
    }

    result = call_moodle_api("core_user_create_users", params)

    if result["success"] and isinstance(result["data"], list):
        return result["data"][0].get("id"), None

    return None, result.get("error", "User creation failed")


# ========================================
# UPDATE / SYNC MOODLE USER PROFILE
# ========================================

def update_moodle_user(
    moodle_user_id,
    username=None,
    firstname=None,
    lastname=None,
    email=None,
    password=None,
):
    """
    Update an existing Moodle user.
    This uses Moodle core_user_update_users.
    """

    if not moodle_user_id:
        return False, "Moodle user id is required"

    params = {
        "users[0][id]": moodle_user_id,
    }

    if username is not None and str(username).strip():
        params["users[0][username]"] = str(username).strip()

    if firstname is not None and str(firstname).strip():
        params["users[0][firstname]"] = str(firstname).strip()

    if lastname is not None and str(lastname).strip():
        params["users[0][lastname]"] = str(lastname).strip()

    if email is not None and str(email).strip():
        params["users[0][email]"] = str(email).strip()

    if password is not None and str(password).strip():
        params["users[0][password]"] = str(password)

    result = call_moodle_api("core_user_update_users", params)

    if result["success"]:
        return True, None

    return False, result.get("error", "Moodle user update failed")


def get_moodle_user_by_id(moodle_user_id):
    """
    Fetch one Moodle user by id.
    """
    if not moodle_user_id:
        return None, "Moodle user id is required"

    params = {
        "field": "id",
        "values[0]": moodle_user_id,
    }

    result = call_moodle_api("core_user_get_users_by_field", params)

    if result["success"] and isinstance(result["data"], list) and result["data"]:
        return result["data"][0], None

    return None, result.get("error", "Could not fetch Moodle user")


def update_moodle_user_profile_from_django_user(user, password=None):
    """
    Sync Django user profile to Moodle profile.
    Expects:
    - Django user has user.profile.moodle_user_id
      OR student row sync already handled elsewhere.
    """

    if not user:
        return False, "Django user is required"

    moodle_user_id = None

    user_profile = getattr(user, "profile", None)
    if user_profile:
        moodle_user_id = getattr(user_profile, "moodle_user_id", None)

    if not moodle_user_id:
        return False, "Moodle user id not found for this user"

    full_name = (user.get_full_name() or "").strip()
    first_name = ""
    last_name = ""

    if full_name:
        name_parts = full_name.split()
        first_name = name_parts[0]
        if len(name_parts) > 1:
            last_name = " ".join(name_parts[1:])
    else:
        first_name = getattr(user, "username", "Student")
        last_name = "User"

    return update_moodle_user(
        moodle_user_id=moodle_user_id,
        username=getattr(user, "username", None),
        firstname=first_name,
        lastname=last_name,
        email=getattr(user, "email", None),
        password=password,
    )