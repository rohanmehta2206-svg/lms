from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from django.contrib import messages
from .forms import RegisterForm
from .models import UserProfile, PendingTeacher

# Moodle API
from teacher.moodle_api import create_moodle_user

from student.models import Student


# =====================================
# HELPER: RESOLVE / SYNC MOODLE USER ID
# =====================================
def resolve_user_moodle_id(user):
    """
    Safe resolver for Moodle user id.

    Order:
    1. Try UserProfile.moodle_user_id
    2. Try Student.moodle_user_id
    3. If found in Student and missing in UserProfile, write it back
    4. If UserProfile does not exist, create it
    """
    moodle_user_id = None

    profile = getattr(user, "profile", None)
    if profile:
        moodle_user_id = getattr(profile, "moodle_user_id", None)

    if moodle_user_id:
        return moodle_user_id

    student = Student.objects.filter(user=user).first()
    if student and getattr(student, "moodle_user_id", None):
        moodle_user_id = student.moodle_user_id

        if profile:
            if not getattr(profile, "moodle_user_id", None):
                profile.moodle_user_id = moodle_user_id
                profile.save(update_fields=["moodle_user_id"])
        else:
            UserProfile.objects.update_or_create(
                user=user,
                defaults={
                    "moodle_user_id": moodle_user_id
                }
            )

        return moodle_user_id

    return None


# =====================================
# HOME PAGE
# =====================================
def home(request):
    return render(request, "accounts/home.html")


# =====================================
# LOGIN VIEW
# =====================================
def login_view(request):
    if request.method == "POST":
        form = AuthenticationForm(request, data=request.POST)

        if form.is_valid():
            user = form.get_user()
            login(request, user)

            # Always rebuild moodle_user_id from DB on login
            resolved_moodle_user_id = resolve_user_moodle_id(user)

            if resolved_moodle_user_id:
                request.session["moodle_user_id"] = resolved_moodle_user_id
                print("Moodle user id linked on login:", resolved_moodle_user_id)
            else:
                request.session.pop("moodle_user_id", None)
                print("No Moodle user id found for this user")

            # Admin login
            if user.is_superuser:
                return redirect("adminpanel:dashboard")

            # Teacher login
            if user.is_staff:
                return redirect("teacher:teacher_dashboard")

            # Student login
            return redirect("/student/dashboard/")

        else:
            username = request.POST.get("username", "").strip()
            password = request.POST.get("password", "")

            # Case 1: teacher already created in Django but pending approval
            pending_teacher_user = User.objects.filter(
                username=username,
                is_staff=True,
                is_superuser=False,
                is_active=False
            ).first()

            if pending_teacher_user and pending_teacher_user.check_password(password):
                messages.error(
                    request,
                    "Your teacher account request is pending admin approval. Please wait until the admin approves your account."
                )
            else:
                # Case 2: teacher request only exists in PendingTeacher table
                pending_teacher_request = PendingTeacher.objects.filter(username=username).first()

                if pending_teacher_request and pending_teacher_request.password == password:
                    messages.error(
                        request,
                        "Your teacher account request is pending admin approval. Please wait until the admin approves your account."
                    )
                else:
                    messages.error(request, "Invalid username or password.")

    else:
        form = AuthenticationForm()

    return render(request, "accounts/login.html", {"form": form})


# =====================================
# REGISTER VIEW
# =====================================
def register_view(request):
    if request.method == "POST":
        form = RegisterForm(request.POST)

        if form.is_valid():
            role = (
                request.POST.get("role")
                or request.POST.get("account_type")
                or request.POST.get("user_type")
                or "teacher"
            ).strip().lower()

            is_student = role == "student"

            password = form.cleaned_data.get("password1")
            username = form.cleaned_data.get("username")
            email = form.cleaned_data.get("email") or f"{username}@example.com"
            firstname = form.cleaned_data.get("first_name") or username
            lastname = form.cleaned_data.get("last_name") or ("Student" if is_student else "Teacher")

            # -------------------------------------
            # STUDENT FLOW (keep working)
            # -------------------------------------
            if is_student:
                user = form.save(commit=False)
                user.is_staff = False
                user.is_active = True
                user.save()

                print("Student Django user created:", user.username)

                try:
                    moodle_user_id, moodle_error = create_moodle_user(
                        username=username,
                        password=password,
                        firstname=firstname,
                        lastname=lastname,
                        email=email
                    )

                    if not moodle_user_id:
                        print("Moodle user creation failed:", moodle_error)
                        user.delete()
                        messages.error(
                            request,
                            f"Moodle user creation failed: {moodle_error or 'Please try again.'}"
                        )
                        return redirect("accounts:register")

                    print("Student Moodle user created:", moodle_user_id)
                    request.session["moodle_user_id"] = moodle_user_id

                except Exception as e:
                    print("Moodle user creation error:", e)
                    user.delete()
                    messages.error(request, "Moodle connection error.")
                    return redirect("accounts:register")

                try:
                    UserProfile.objects.update_or_create(
                        user=user,
                        defaults={
                            "moodle_user_id": moodle_user_id,
                        }
                    )
                    print("UserProfile created successfully.")
                except Exception as e:
                    print("UserProfile creation error:", e)
                    user.delete()
                    messages.error(request, "User profile creation failed.")
                    return redirect("accounts:register")

                try:
                    Student.objects.update_or_create(
                        user=user,
                        defaults={
                            "username": username,
                            "email": email,
                            "password": password,
                            "moodle_user_id": moodle_user_id,
                        }
                    )
                    print("Student profile created successfully.")
                except Exception as e:
                    print("Student profile creation error:", e)
                    user.delete()
                    messages.error(request, "Student profile creation failed.")
                    return redirect("accounts:register")

                login(request, user)
                request.session["moodle_user_id"] = moodle_user_id
                messages.success(request, "Student account created successfully!")
                return redirect("/student/dashboard/")

            # -------------------------------------
            # TEACHER FLOW (save only in PendingTeacher)
            # -------------------------------------
            else:
                # block duplicates in Django User
                if User.objects.filter(username=username).exists():
                    messages.error(request, "This username is already registered.")
                    return redirect("accounts:register")

                if User.objects.filter(email=email).exists():
                    messages.error(request, "This email is already registered.")
                    return redirect("accounts:register")

                # block duplicates in PendingTeacher
                if PendingTeacher.objects.filter(username=username).exists():
                    messages.error(
                        request,
                        "A teacher request with this username is already pending admin approval."
                    )
                    return redirect("accounts:register")

                PendingTeacher.objects.create(
                    username=username,
                    email=email,
                    first_name=firstname,
                    last_name=lastname,
                    password=password,
                )

                print("Pending teacher request created:", username)

                request.session.pop("moodle_user_id", None)
                messages.success(
                    request,
                    "Teacher account request submitted successfully. After admin approval, your Django and Moodle accounts will be created with the same password."
                )
                return redirect("accounts:login")

        else:
            messages.error(request, "Please correct the form errors.")

    else:
        form = RegisterForm()

    return render(request, "accounts/register.html", {"form": form})


# =====================================
# LOGOUT VIEW
# =====================================
def logout_view(request):
    request.session.pop("moodle_user_id", None)
    logout(request)
    return redirect("core:home")