import os
import subprocess
import requests

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.http import FileResponse, HttpResponse
from django.contrib import messages
from .models import Course, Section, Module
from .forms import CourseForm
from django.views.decorators.clickjacking import xframe_options_exempt

# ==========================================
# MOODLE API CONFIG
# ==========================================

MOODLE_URL = "http://127.0.0.1/moodle/webservice/rest/server.php"
MOODLE_TOKEN = "53a8b7519e7d735edc9b6423e84f2b54"


# ==========================================
# MOODLE API FUNCTIONS
# ==========================================

def create_course_in_moodle(course):
    data = {
        "wstoken": MOODLE_TOKEN,
        "wsfunction": "core_course_create_courses",
        "moodlewsrestformat": "json",
        "courses[0][fullname]": course.title,
        "courses[0][shortname]": course.short_name,
        "courses[0][categoryid]": course.category.moodle_category_id,
        "courses[0][format]": "topics",
        "courses[0][numsections]": course.number_of_sections,
    }

    response = requests.post(MOODLE_URL, data=data)
    result = response.json()
    print("🎯 Create Course:", result)
    return result


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


def send_module_to_moodle(course_id, section_number, title, player_url):
    try:
        data = {
            "wstoken": MOODLE_TOKEN,
            "wsfunction": "local_djangoapi_create_module",
            "moodlewsrestformat": "json",
            "courseid": course_id,
            "sectionnumber": section_number,
            "name": title,
            "video_url": player_url
        }

        response = requests.post(MOODLE_URL, data=data)

        print("Module status code:", response.status_code)
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
    data = {
        "wstoken": MOODLE_TOKEN,
        "wsfunction": "mod_page_create_pages",
        "moodlewsrestformat": "json",
        "pages[0][courseid]": course_id,
        "pages[0][name]": title,
        "pages[0][content]": content,
        "pages[0][section]": section_number
    }

    response = requests.post(MOODLE_URL, data=data)

    print("Theory status code:", response.status_code)
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
            course.save()

            if not course.category or not course.category.moodle_category_id:
                course.delete()
                messages.error(request, "Please choose a Moodle-connected category.")
                return redirect("teacher:course_list")

            # Create Django sections
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
                course.save()

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

        # Save Django title first
        section.title = new_title
        section.save()

        # Then try Moodle update
        if section.course.moodle_course_id and section.moodle_section_id:
            result = update_section_in_moodle(
                section.course.moodle_course_id,
                section.moodle_section_id,
                new_title
            )

            # Do NOT rollback Django title here.
            # Moodle may actually update successfully even if response parsing is imperfect.
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
    return render(request, "teacher/play_module.html", {"module": module})


# ==========================================
# MODULE BUILDER
# ==========================================

@login_required
def module_builder(request, section_id):
    section = get_object_or_404(Section, id=section_id)

    if request.method == "POST":
        content_type = request.POST.get("type")
        title = request.POST.get("title")

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

                if section.course.moodle_course_id and section.moodle_section_number is not None:
                    send_module_to_moodle(
                        section.course.moodle_course_id,
                        section.moodle_section_number,
                        module.title,
                        player_url
                    )

                messages.success(request, "Video uploaded successfully.")

            # THEORY
            elif content_type == "theory":
                module.theory = request.POST.get("theory")
                module.save()

                if section.course.moodle_course_id and section.moodle_section_number is not None:
                    send_theory_to_moodle(
                        section.course.moodle_course_id,
                        section.moodle_section_number,
                        module.title,
                        module.theory
                    )

                messages.success(request, "Theory added successfully.")

            # QUIZ
            elif content_type == "quiz":
                module.quiz_question = request.POST.get("quiz_question")
                module.quiz_options = request.POST.get("quiz_options")
                module.quiz_answer = request.POST.get("quiz_answer")
                module.save()

                quiz_content = f"""
                <h3>{module.quiz_question}</h3>
                <p>{module.quiz_options}</p>
                <p><b>Answer:</b> {module.quiz_answer}</p>
                """

                if section.course.moodle_course_id and section.moodle_section_number is not None:
                    send_theory_to_moodle(
                        section.course.moodle_course_id,
                        section.moodle_section_number,
                        module.title,
                        quiz_content
                    )

                messages.success(request, "Quiz added successfully.")

        except Exception as e:
            print("ERROR:", str(e))
            module.delete()
            messages.error(request, f"Something went wrong: {str(e)}")

        return redirect("teacher:module_builder", section_id=section.id)

    modules = Module.objects.filter(section=section).order_by("-id")

    return render(
        request,
        "teacher/module_builder.html",
        {"section": section, "modules": modules}
    )


# ==========================================
# STREAM DASH FILES
# ==========================================

def serve_dash(request, path):
    base_path = settings.LMS_STORAGE_PATH
    file_path = os.path.join(base_path, path)

    if not os.path.exists(file_path):
        return HttpResponse("File not found", status=404)

    if file_path.endswith(".mpd"):
        content_type = "application/dash+xml"
    elif file_path.endswith(".m4s"):
        content_type = "video/mp4"
    else:
        content_type = "application/octet-stream"

    return FileResponse(open(file_path, "rb"), content_type=content_type)