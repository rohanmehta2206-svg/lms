from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib import messages
from .forms import RegisterForm

# Moodle API
from teacher.moodle_api import (
    create_moodle_user,
    create_teacher_parent_category,
    create_default_child_categories
)


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

            moodle_user_id = request.session.get("moodle_user_id")

            if moodle_user_id:
                print("Moodle user id found in session:", moodle_user_id)
            else:
                print("No Moodle user id found in session")

            # Teacher login
            if user.is_staff or user.is_superuser:
                return redirect("teacher:teacher_dashboard")

            # Student login
            return redirect("/student/dashboard/")

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

            # -------------------------------------
            # Create Django user
            # -------------------------------------
            user = form.save(commit=False)

            if is_student:
                user.is_staff = False
            else:
                user.is_staff = True

            user.save()

            print("Django user created:", user.username)
            print("Selected role:", role)

            password = form.cleaned_data.get("password1")

            username = user.username
            email = user.email if user.email else f"{username}@example.com"
            firstname = user.first_name if user.first_name else username
            lastname = user.last_name if user.last_name else ("Student" if is_student else "Teacher")

            # =====================================
            # CREATE MOODLE USER
            # =====================================
            try:
                moodle_user_id = create_moodle_user(
                    username=username,
                    password=password,
                    firstname=firstname,
                    lastname=lastname,
                    email=email
                )

                if not moodle_user_id:
                    messages.error(
                        request,
                        "Moodle user creation failed. Please try again."
                    )
                    user.delete()
                    return redirect("accounts:register")

                print("Moodle user created:", moodle_user_id)

                # Save in session
                request.session["moodle_user_id"] = moodle_user_id

            except Exception as e:
                print("Moodle user creation error:", e)

                user.delete()

                messages.error(
                    request,
                    "Moodle connection error."
                )

                return redirect("accounts:register")

            # =====================================
            # CREATE TEACHER CATEGORY ONLY
            # =====================================
            if not is_student:
                try:
                    print("Creating teacher parent category...")

                    parent_category_id = create_teacher_parent_category(username)

                    print("Parent category ID:", parent_category_id)

                    if parent_category_id:
                        create_default_child_categories(parent_category_id)

                except Exception as e:
                    print("Category creation error:", e)

            # -------------------------------------
            # Login user after register
            # -------------------------------------
            login(request, user)

            messages.success(request, "Account created successfully!")

            # -------------------------------------
            # Redirect by role
            # -------------------------------------
            if is_student:
                return redirect("/student/dashboard/")
            else:
                return redirect("teacher:teacher_dashboard")

        else:
            messages.error(request, "Please correct the form errors.")

    else:
        form = RegisterForm()

    return render(request, "accounts/register.html", {"form": form})


# =====================================
# LOGOUT VIEW
# =====================================
def logout_view(request):
    logout(request)
    return redirect("accounts:login")