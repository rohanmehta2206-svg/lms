# 📚 Instructor LMS — Cryptographic Adaptive Learning Management System

A **full-featured Learning Management System (LMS)** built with Django, integrated with **Moodle** for course synchronization, and equipped with **cryptographic audit logging**, **anti-cheating mechanisms**, and **digital certificate issuance**.

---

## 📋 Table of Contents

- [About the Project](#about-the-project)
- [Features](#features)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [System Requirements](#system-requirements)
- [Installation & Setup](#installation--setup)
- [Database Configuration](#database-configuration)
- [Moodle Integration](#moodle-integration)
- [User Roles](#user-roles)
- [App Overview](#app-overview)
- [URL Routes](#url-routes)
- [Anti-Cheating & Security](#anti-cheating--security)
- [Certificate System](#certificate-system)
- [Screenshots](#screenshots)

---

## 📌 About the Project

**Instructor LMS** is a Django-based Learning Management System designed for academic institutions. It provides a complete e-learning experience with:

- Teachers creating and managing courses, sections, and modules (video, quiz, theory, materials)
- Students enrolling in courses and tracking their progress
- Admin managing users, courses, certificates, and system settings
- Full **bi-directional Moodle synchronization** for courses, users, enrollments, and completions
- **Tamper-proof audit logs** using SHA-256 hash chaining for video events, webcam snapshots, and tab switch logs

---

## ✨ Features

### 👨‍🏫 Teacher
- Create and manage courses with categories, sections, and modules
- Upload video modules (MP4 + DASH streaming), theory content, quiz questions, and material files
- Publish / unpublish courses and modules (draft mode)
- View student progress and quiz attempts
- Full Moodle course/section/module synchronization

### 🧑‍🎓 Student
- Browse and enroll in available courses
- Watch video modules with real-time progress tracking (heartbeat system)
- Complete quizzes with instant scoring
- Read theory modules and download material files
- Download and verify digital certificates upon course completion
- Progress tracker dashboard

### 🛡️ Admin
- Approve / reject pending teacher registration requests
- Manage all users, courses, and enrollments
- Audit reports and system monitoring
- Revoke issued certificates with reason tracking
- Configure system settings (Moodle URL, token, watch %, streaming)
- Certificate settings management (logo, signature, seal)

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| **Backend** | Python 3.x, Django 4.x |
| **Database** | PostgreSQL |
| **LMS Integration** | Moodle (REST Web Services API) |
| **Video Streaming** | DASH (Dynamic Adaptive Streaming over HTTP) |
| **Security** | SHA-256 Hash Chaining (Immutable Audit Logs) |
| **Frontend** | HTML5, CSS3, JavaScript (Django Templates) |
| **File Storage** | Django Media + External LMS Storage (`C:/lms_storage`) |
| **Authentication** | Django Auth (Session-based) |

---

## 📁 Project Structure

```
instructor/                     ← Django project root
│
├── instructor/                 ← Project settings & main URLs
│   ├── settings.py
│   ├── urls.py
│   ├── wsgi.py
│   └── asgi.py
│
├── accounts/                   ← Authentication & user profiles
│   ├── models.py               → UserProfile, PendingTeacher
│   ├── views.py                → Login, Register, Logout
│   ├── forms.py
│   └── urls.py
│
├── teacher/                    ← Teacher course management
│   ├── models.py               → Category, Course, Section, Module, QuizQuestion, CertificateSettings
│   ├── views.py                → Dashboard, Course/Section/Module CRUD, Streaming
│   ├── moodle_api.py           → Full Moodle REST API integration
│   ├── forms.py
│   └── urls.py
│
├── student/                    ← Student learning experience
│   ├── models.py               → Student, Enrollment, Progress, QuizAttempt,
│   │                              Certificate, VideoWatchProgress,
│   │                              VideoWatchEvent, WebcamSnapshot, TabSwitchLog
│   ├── views.py                → Dashboard, Video Player, Quiz, Certificate, Enrollment
│   └── urls.py
│
├── adminpanel/                 ← Admin control panel
│   ├── models.py               → SystemSettings
│   ├── views.py                → Dashboard, User Mgmt, Reports, Certificates
│   └── urls.py
│
├── core/                       ← Landing page / home
│
├── static/                     ← CSS, JS, images
├── media/                      ← Uploaded files (videos, thumbnails, certificates)
├── templates/                  ← All HTML templates
└── manage.py
```

---

## ⚙️ System Requirements

- Python **3.10+**
- PostgreSQL **13+**
- Moodle **3.9+** (with Web Services enabled)
- pip (Python package manager)
- Windows / Linux / macOS

---

## 🚀 Installation & Setup

### 1. Clone the Repository

```bash
git clone <your-repo-url>
cd instructor
```

### 2. Create & Activate Virtual Environment

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Linux / macOS
python3 -m venv venv
source venv/bin/activate
```


### 3. Install Dependencies

Install all required Python packages using the provided `requirements.txt` file for exact version compatibility:

```bash
# Windows/Linux/macOS
pip install -r requirements.txt
```

### 4. Configure Database

Edit `instructor/settings.py`:

```python
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'teacher',       # your database name
        'USER': 'tuser',         # your database user
        'PASSWORD': 'teacher',   # your database password
        'HOST': 'localhost',
        'PORT': '5432',
    }
}
```

### 5. Configure Moodle Settings

```python
# instructor/settings.py
MOODLE_URL   = "http://localhost/moodle"
MOODLE_TOKEN = "your_moodle_webservice_token"
```

> You can also configure Moodle settings dynamically from the **Admin Panel → System Settings** page after the server is running.

### 6. Run Migrations

```bash
python manage.py makemigrations
python manage.py migrate
```

### 7. Create Superuser (Admin)

```bash
python manage.py createsuperuser
```

### 8. Collect Static Files

```bash
python manage.py collectstatic
```


### 9. Start Development Server

```bash
python manage.py runserver
```

Visit: [http://127.0.0.1:8000](http://127.0.0.1:8000)

---

## 🚀 Quick Start on a New PC

1. **Clone or copy the project folder** to your PC.
2. **Install Python 3.10+** and [PostgreSQL 13+](https://www.postgresql.org/download/).
3. **Create and activate a virtual environment:**
    - Windows:  
      `python -m venv venv && venv\Scripts\activate`
    - Linux/macOS:  
      `python3 -m venv venv && source venv/bin/activate`
4. **Install dependencies:**
    - `pip install -r requirements.txt`
5. **Set up PostgreSQL database:**
    - Create user and database as shown in [Database Configuration](#database-configuration).
6. **Configure `instructor/settings.py`** for your database and Moodle settings.
7. **Run migrations:**
    - `python manage.py makemigrations`
    - `python manage.py migrate`
8. **Create a superuser:**
    - `python manage.py createsuperuser`
9. **Collect static files:**
    - `python manage.py collectstatic`
10. **Run the server:**
     - `python manage.py runserver`
11. **Access the app:**
     - Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your browser.

> For Moodle integration, ensure your Moodle instance is running and configured as described below.

---

## 🗄️ Database Configuration

The project uses **PostgreSQL**. Create the database before running migrations:

```sql
-- Run in psql or pgAdmin
CREATE USER tuser WITH PASSWORD 'teacher';
CREATE DATABASE teacher OWNER tuser;
GRANT ALL PRIVILEGES ON DATABASE teacher TO tuser;
```

---

## 🔗 Moodle Integration

The system uses **Moodle REST Web Services** via the `teacher/moodle_api.py` module.

### What Gets Synced

| Action | Synced to Moodle |
|---|---|
| Register Student | ✅ Creates Moodle user |
| Approve Teacher | ✅ Creates Moodle user + assigns teacher role |
| Create Course | ✅ Creates Moodle course + category |
| Create Section | ✅ Syncs section to Moodle |
| Add Video Module | ✅ Creates Moodle page activity |
| Student Enrolls | ✅ Enrolls student in Moodle course |
| Complete Module | ✅ Marks activity complete in Moodle |
| Issue Certificate | ✅ Records certificate in Moodle |

### Enabling Moodle Web Services

1. Go to **Moodle → Site Admin → Plugins → Web Services → Enable Web Services**
2. Generate a token with the required functions
3. Install the custom `local_djangoapi` Moodle plugin for advanced features (completion marking, certificate recording)

---

## 👤 User Roles

| Role | Access Level | Description |
|---|---|---|
| **Admin** (superuser) | Full access | Manages all users, courses, settings |
| **Teacher** (is_staff) | Teacher dashboard | Creates and manages courses/modules |
| **Student** | Student dashboard | Enrolls in courses, watches content |

### Registration Flow

```
Student Registration  →  Instant active account  →  Moodle user created
Teacher Registration  →  Pending (PendingTeacher table)  →  Admin approval  →  Moodle user created
```

---

## 📦 App Overview

### `accounts` App
Handles user authentication — login, registration, and logout. Manages `UserProfile` (linked to Django User) and `PendingTeacher` (staging table for teacher requests awaiting admin approval).

### `teacher` App
Full course management for teachers:
- **Category → Course → Section → Module** hierarchy
- Module types: `video`, `theory`, `quiz`, `material`
- DASH video streaming support
- Moodle sync via `moodle_api.py`
- `CertificateSettings` model for customizing certificate appearance

### `student` App
Student learning experience:
- Course enrollment and progress tracking
- Video heartbeat system (records every few seconds of watch time)
- Quiz attempt system with automatic scoring
- Certificate generation and PDF download
- Anti-cheating: webcam snapshots + tab switch logging

### `adminpanel` App
Admin control panel:
- Approve/reject teacher accounts
- Manage all users and courses
- Audit reports (view immutable logs)
- Certificate control (view, revoke)
- `SystemSettings` model (Moodle config, streaming, compliance settings)

### `core` App
Home/landing page routing.

---

## 🌐 URL Routes

| Prefix | App | Description |
|---|---|---|
| `/` | core | Landing / home page |
| `/accounts/login/` | accounts | Login page |
| `/accounts/register/` | accounts | Registration |
| `/accounts/logout/` | accounts | Logout |
| `/teacher/dashboard/` | teacher | Teacher dashboard |
| `/teacher/courses/` | teacher | Manage courses |
| `/teacher/courses/create/` | teacher | Create new course |
| `/teacher/module-builder/<id>/` | teacher | Add modules to section |
| `/teacher/play-module/<id>/` | teacher | Preview module |
| `/teacher/drafts/` | teacher | View draft content |
| `/student/dashboard/` | student | Student dashboard |
| `/student/courses/` | student | My enrolled courses |
| `/student/enroll/<id>/` | student | Enroll in course |
| `/student/play-video/<id>/` | student | Watch video module |
| `/student/take-quiz/<id>/` | student | Take quiz |
| `/student/certificates/` | student | My certificates |
| `/student/certificate/download/<id>/` | student | Download certificate PDF |
| `/adminpanel/` | adminpanel | Admin dashboard |
| `/adminpanel/users/` | adminpanel | User management |
| `/adminpanel/courses/` | adminpanel | Course management |
| `/adminpanel/certificates/` | adminpanel | Certificate control |
| `/adminpanel/reports/` | adminpanel | Audit reports |
| `/adminpanel/settings/` | adminpanel | System settings |
| `/admin/` | Django Admin | Django admin panel |

---

## 🔒 Anti-Cheating & Security

The system includes several anti-cheating mechanisms:

### 1. Video Watch Heartbeat
- Student's browser sends heartbeats every few seconds during video playback
- Tracks `watched_seconds`, `watched_percent`, `last_position`, `max_position_reached`
- Module is marked complete only when **watch percentage ≥ 90%** (configurable in System Settings)

### 2. Webcam Snapshots (`WebcamSnapshot`)
- Periodic webcam photos are captured during video modules
- Stored as **immutable records** with SHA-256 hash chaining

### 3. Tab Switch Logging (`TabSwitchLog`)
- Detects and logs every time a student switches tabs during a module
- Each log entry is **immutable** with hash chaining

### 4. Video Watch Events (`VideoWatchEvent`)
- Records every `play`, `pause`, `seek`, `heartbeat`, and `ended` event
- **Append-only** — records cannot be updated or deleted
- Hash-chained for tamper detection

### Immutable Log Pattern
All audit log models extend `ImmutableLogMixin`:
```
previous_hash → SHA-256(previous_hash | event_data) → current_hash
```
This creates a **blockchain-style tamper-proof chain** of events.

---

## 🎓 Certificate System

### Issuance
- Certificate is auto-issued when a student completes all modules in a course
- Unique `certificate_code` is generated per student per course
- Certificate is synced to Moodle via `local_djangoapi_issue_certificate`

### Verification
- QR code or direct URL-based verification
- Public verification page: `/student/certificate/verify/<course_id>/<user_id>/`

### Revocation
- Admin can revoke any certificate with a reason
- Revoked certificates show status as `revoked` with `revoked_at` timestamp

### Customization (`CertificateSettings`)
- Title, subtitle, organization name
- Issuer name, signer name and role
- Signature image and seal image upload
- Verify label text

---

## 📸 Screenshots

> *(Add screenshots of your project here for the report)*

| Screen | Description |
|---|---|
| Login Page | Student / Teacher / Admin login |
| Student Dashboard | Enrolled courses, progress overview |
| Course Detail | Section and module list |
| Video Player | DASH streaming with progress bar |
| Quiz Page | MCQ and True/False questions |
| Certificate | Generated PDF certificate |
| Admin Dashboard | User management, reports |
| Teacher Dashboard | Course creation and management |

---

## 👨‍💻 Developer Notes

- **Secret Key**: Change `SECRET_KEY` in `settings.py` before production deployment
- **DEBUG**: Set `DEBUG = False` in production
- **ALLOWED_HOSTS**: Add your domain/IP in `settings.py`
- **LMS Storage**: DASH video files are stored at `C:/lms_storage` (configurable via `LMS_STORAGE_PATH`)
- **Media Files**: Uploaded files are stored in the `media/` directory

---

## 📄 License

This project is developed for academic/educational purposes.

---

> **Project:** Cryptographic Adaptive LMS  
> **Framework:** Django (Python)  
> **Database:** PostgreSQL  
> **Integration:** Moodle LMS
