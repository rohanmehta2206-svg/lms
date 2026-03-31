import os
import requests
from django.conf import settings


# ========================================
# MOODLE CONFIGURATION
# ========================================

MOODLE_BASE_URL = getattr(settings, "MOODLE_BASE_URL", "http://127.0.0.1/moodle").rstrip("/")
MOODLE_TOKEN = getattr(settings, "MOODLE_TOKEN", "53a8b7519e7d735edc9b6423e84f2b54")

MOODLE_API_URL = f"{MOODLE_BASE_URL}/webservice/rest/server.php"
MOODLE_UPLOAD_URL = f"{MOODLE_BASE_URL}/webservice/upload.php"

MOODLE_ADMIN_ID = getattr(settings, "MOODLE_ADMIN_ID", 2)
MOODLE_TEACHER_ROLE = getattr(settings, "MOODLE_TEACHER_ROLE", 3)

DEFAULT_TIMEOUT = 30


# ========================================
# GENERIC MOODLE API CALL
# ========================================

def call_moodle_api(function_name, params=None, timeout=DEFAULT_TIMEOUT):
    if params is None:
        params = {}

    payload = {
        "wstoken": MOODLE_TOKEN,
        "wsfunction": function_name,
        "moodlewsrestformat": "json",
    }
    payload.update(params)

    try:
        response = requests.post(
            MOODLE_API_URL,
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

    normalized_name = category_name.strip().lower()

    exact_matches = []
    for category in categories:
        moodle_name = str(category.get("name", "")).strip().lower()
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

def enroll_user_to_course(user_id, course_id, role_id=MOODLE_TEACHER_ROLE):
    params = {
        "enrolments[0][roleid]": role_id,
        "enrolments[0][userid]": user_id,
        "enrolments[0][courseid]": course_id,
    }

    result = call_moodle_api("enrol_manual_enrol_users", params)

    if result["success"]:
        return True, None

    return False, result.get("error", "Enrollment failed")


def enroll_admin_to_course(course_id):
    return enroll_user_to_course(
        MOODLE_ADMIN_ID,
        course_id,
        MOODLE_TEACHER_ROLE
    )


# ========================================
# UPLOAD IMAGE TO MOODLE
# ========================================

def upload_course_image(image_path):
    try:
        if not os.path.exists(image_path):
            return None, f"Image file not found: {image_path}"

        with open(image_path, "rb") as f:
            response = requests.post(
                MOODLE_UPLOAD_URL,
                params={
                    "token": MOODLE_TOKEN,
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