from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib import messages

from teacher.models import Course
from teacher.moodle_api import (
    create_moodle_user,
    create_teacher_parent_category,
    create_default_child_categories,
)
from accounts.models import UserProfile, PendingTeacher


@login_required
def admin_dashboard(request):
    total_users = User.objects.count()
    total_students = User.objects.filter(is_staff=False, is_superuser=False).count()
    total_teachers = User.objects.filter(is_staff=True, is_superuser=False).count()
    total_admins = User.objects.filter(is_superuser=True).count()
    total_courses = Course.objects.count()

    context = {
        'total_users': total_users,
        'total_students': total_students,
        'total_teachers': total_teachers,
        'total_admins': total_admins,
        'total_courses': total_courses,
    }

    return render(request, 'adminpanel/dashboard.html', context)


@login_required
def user_management(request):
    users = User.objects.all().order_by('-date_joined')

    user_list = []
    for user in users:
        if user.is_superuser:
            role = 'Admin'
        elif user.is_staff:
            role = 'Teacher'
        else:
            role = 'Student'

        full_name = user.get_full_name().strip()
        if not full_name:
            full_name = user.username

        user_list.append({
            'id': user.id,
            'username': user.username,
            'full_name': full_name,
            'email': user.email,
            'role': role,
            'is_active': user.is_active,
            'date_joined': user.date_joined,
            'approval_status': 'Approved',
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
        })

    context = {
        'users': user_list,
        'pending_teachers': pending_teachers,
        'total_users': len(user_list),
        'total_students': sum(1 for user in user_list if user['role'] == 'Student'),
        'total_teachers': sum(1 for user in user_list if user['role'] == 'Teacher'),
        'total_admins': sum(1 for user in user_list if user['role'] == 'Admin'),
        'pending_teacher_count': len(pending_teachers),
    }

    return render(request, 'adminpanel/users.html', context)


@login_required
def approve_teacher(request, user_id):
    if not request.user.is_superuser:
        messages.error(request, "Only admin can approve teacher requests.")
        return redirect('adminpanel:users')

    pending_teacher = get_object_or_404(PendingTeacher, id=user_id)

    username = pending_teacher.username
    email = pending_teacher.email if pending_teacher.email else f"{username}@example.com"
    first_name = pending_teacher.first_name if pending_teacher.first_name else username
    last_name = pending_teacher.last_name if pending_teacher.last_name else "Teacher"
    raw_password = pending_teacher.password

    # Safety checks
    if User.objects.filter(username=username).exists():
        messages.error(request, f"A Django user with username '{username}' already exists.")
        return redirect('adminpanel:users')

    if User.objects.filter(email=email).exists():
        messages.error(request, f"A Django user with email '{email}' already exists.")
        return redirect('adminpanel:users')

    try:
        # 1. Create Django teacher user
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

        # 2. Create Moodle teacher user with SAME password
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

        # 3. Save Moodle user id in UserProfile
        UserProfile.objects.update_or_create(
            user=teacher_user,
            defaults={
                'moodle_user_id': moodle_user_id,
            }
        )

        # 4. Create teacher parent + default categories
        try:
            parent_category_id, category_error = create_teacher_parent_category(username)

            if parent_category_id:
                create_default_child_categories(parent_category_id)
                print("Teacher categories created successfully.")
            else:
                print("Teacher category creation failed:", category_error)

        except Exception as e:
            print("Teacher category creation error:", e)

        # 5. Delete pending request after successful approval
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
    if not request.user.is_superuser:
        messages.error(request, "Only admin can reject teacher requests.")
        return redirect('adminpanel:users')

    pending_teacher = get_object_or_404(PendingTeacher, id=user_id)
    username = pending_teacher.username
    pending_teacher.delete()

    messages.success(request, f"Teacher request '{username}' rejected successfully.")
    return redirect('adminpanel:users')


@login_required
def audit_reports(request):
    total_users = User.objects.count()
    total_students = User.objects.filter(is_staff=False, is_superuser=False).count()
    total_teachers = User.objects.filter(is_staff=True, is_superuser=False).count()
    total_admins = User.objects.filter(is_superuser=True).count()
    total_courses = Course.objects.count()
    active_users = User.objects.filter(is_active=True).count()
    inactive_users = User.objects.filter(is_active=False).count()

    recent_users_qs = User.objects.all().order_by('-date_joined')[:10]

    recent_users = []
    for user in recent_users_qs:
        if user.is_superuser:
            role = 'Admin'
        elif user.is_staff:
            role = 'Teacher'
        else:
            role = 'Student'

        full_name = user.get_full_name().strip()
        if not full_name:
            full_name = user.username

        recent_users.append({
            'username': user.username,
            'full_name': full_name,
            'email': user.email,
            'role': role,
            'is_active': user.is_active,
            'date_joined': user.date_joined,
        })

    context = {
        'total_users': total_users,
        'total_students': total_students,
        'total_teachers': total_teachers,
        'total_admins': total_admins,
        'total_courses': total_courses,
        'active_users': active_users,
        'inactive_users': inactive_users,
        'recent_users': recent_users,
    }

    return render(request, 'adminpanel/reports.html', context)


@login_required
def course_management(request):
    courses = Course.objects.all().order_by('-id')

    course_list = []
    published_count = 0
    unpublished_count = 0

    for course in courses:
        is_published = getattr(course, 'is_published', False)
        if is_published:
            published_count += 1
        else:
            unpublished_count += 1

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
            'moodle_course_id': getattr(course, 'moodle_course_id', None),
        })

    context = {
        'courses': course_list,
        'total_courses': len(course_list),
        'published_courses': published_count,
        'unpublished_courses': unpublished_count,
    }

    return render(request, 'adminpanel/courses.html', context)


@login_required
def certificate_control(request):
    courses = Course.objects.all().order_by('-id')[:10]

    certificate_list = []
    issued_count = 0
    pending_count = 0
    revoked_count = 0

    for index, course in enumerate(courses, start=1):
        moodle_course_id = getattr(course, 'moodle_course_id', None)
        is_published = getattr(course, 'is_published', False)

        if is_published:
            status = 'Issued'
            issued_count += 1
        else:
            status = 'Pending'
            pending_count += 1

        certificate_list.append({
            'id': index,
            'student_name': f'Student {index}',
            'course_title': getattr(course, 'title', ''),
            'course_code': getattr(course, 'course_code', ''),
            'certificate_code': f'CERT-{1000 + index}',
            'verification_status': 'Verified' if moodle_course_id else 'Not Synced',
            'status': status,
            'issued_date': getattr(course, 'id', ''),
        })

    context = {
        'certificates': certificate_list,
        'total_certificates': len(certificate_list),
        'issued_certificates': issued_count,
        'pending_certificates': pending_count,
        'revoked_certificates': revoked_count,
    }

    return render(request, 'adminpanel/certificates.html', context)


@login_required
def settings_compliance(request):
    total_courses = Course.objects.count()

    synced_courses = Course.objects.filter(moodle_course_id__isnull=False).count()
    unsynced_courses = Course.objects.filter(moodle_course_id__isnull=True).count()

    published_courses = Course.objects.filter(is_published=True).count()
    unpublished_courses = Course.objects.filter(is_published=False).count()

    system_settings = [
        {
            'title': 'Video Host Configuration',
            'value': 'Configured',
            'description': 'Controls the video storage and streaming source used in the platform.',
            'status': 'Active',
        },
        {
            'title': 'Token Security',
            'value': 'Enabled',
            'description': 'Used for secure communication and protected access control in Moodle integration.',
            'status': 'Protected',
        },
        {
            'title': 'Certificate Signer',
            'value': 'Configured',
            'description': 'Used for certificate authority, signature details, and validation support.',
            'status': 'Active',
        },
        {
            'title': 'QR Verification',
            'value': 'Enabled',
            'description': 'Supports certificate verification flow using QR-based validation.',
            'status': 'Protected',
        },
        {
            'title': 'Watch Validation Rules',
            'value': '90% Minimum',
            'description': 'Used to validate whether a student watched enough video before completion.',
            'status': 'Enforced',
        },
        {
            'title': 'Quiz Completion Rules',
            'value': 'Enabled',
            'description': 'Ensures quiz completion is included in guided learning flow and validation.',
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
            'name': 'Course Publish Control',
            'status': 'Good' if published_courses > 0 else 'Pending',
            'detail': f'{published_courses} published / {unpublished_courses} unpublished',
        },
        {
            'name': 'Certificate Verification',
            'status': 'Enabled',
            'detail': 'QR verification flow available in certificate module',
        },
        {
            'name': 'Secure Learning Flow',
            'status': 'Enabled',
            'detail': 'Locked progression and completion validation are active',
        },
        {
            'name': 'Audit Visibility',
            'status': 'Enabled',
            'detail': 'Admin reports are available for system monitoring',
        },
    ]

    context = {
        'total_courses': total_courses,
        'synced_courses': synced_courses,
        'unsynced_courses': unsynced_courses,
        'published_courses': published_courses,
        'unpublished_courses': unpublished_courses,
        'system_settings': system_settings,
        'compliance_checks': compliance_checks,
    }

    return render(request, 'adminpanel/settings.html', context)