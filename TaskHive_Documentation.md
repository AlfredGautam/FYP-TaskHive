# TaskHive — Complete Feature & Workflow Documentation

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Technology Stack](#2-technology-stack)
3. [System Architecture](#3-system-architecture)
4. [Pages & Features](#4-pages--features)
   - 4.1 [Landing Page (Dashboard)](#41-landing-page-dashboard)
   - 4.2 [Login / Register Page](#42-login--register-page)
   - 4.3 [User Home Page](#43-user-home-page)
   - 4.4 [Workspace (Main App)](#44-workspace-main-app)
   - 4.5 [Analytics Page](#45-analytics-page)
   - 4.6 [CodeSpace (Code Editor)](#46-codespace-code-editor)
   - 4.7 [Profile & Settings Page](#47-profile--settings-page)
   - 4.8 [Public Profile Page](#48-public-profile-page)
5. [Data Models](#5-data-models)
6. [API Endpoints](#6-api-endpoints)
7. [User Workflow (End-to-End)](#7-user-workflow-end-to-end)
8. [Role-Based Access Control](#8-role-based-access-control)
9. [Notification System](#9-notification-system)
10. [Security Features](#10-security-features)

---

## 1. Project Overview

**TaskHive** is a full-stack team collaboration and project management web application built as a Final Year Project. It provides teams with Kanban-style task boards, project management, file sharing, an integrated code editor, analytics dashboards, and real-time notifications — all wrapped in a futuristic neon-themed UI.

### Key Highlights

- **Team-Based Collaboration** — Create or join teams, invite members, assign roles.
- **Kanban Task Boards** — Drag-and-drop tasks across Todo / In Progress / Done columns.
- **Project Management** — Group tasks under projects with status tracking.
- **Integrated Code Editor** — Monaco-powered CodeSpace with file management.
- **Analytics Dashboard** — Charts and summaries of task/project progress.
- **Approval Workflow** — Team heads can review and approve member requests.
- **Activity Logging** — Full audit trail of all team actions.
- **Notification System** — In-app notifications with deadline reminders.
- **Profile System** — Customizable user profiles with avatars, cover photos, bios, and social links.

---

## 2. Technology Stack

| Layer        | Technology                                                       |
|--------------|------------------------------------------------------------------|
| **Backend**  | Python 3, Django 5.2                                             |
| **Frontend** | Vue.js 2.6, Tailwind CSS, Font Awesome 6                        |
| **Database** | SQLite (development), Django ORM                                 |
| **Code Editor** | Monaco Editor (VS Code engine)                               |
| **Charts**   | Chart.js                                                         |
| **Auth**     | Django Sessions, Google OAuth 2.0, Custom Email Authentication   |
| **Email**    | SMTP (Django mail backend)                                       |
| **Fonts**    | Orbitron (headings), Roboto Mono (body)                          |
| **Icons**    | Font Awesome 6.4                                                 |

---

## 3. System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        CLIENT (Browser)                     │
│  Vue.js 2 + Tailwind CSS + Monaco Editor + Chart.js         │
└──────────────────────────┬──────────────────────────────────┘
                           │  REST API (JSON)
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                     DJANGO BACKEND                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐  │
│  │  Views   │  │  Models  │  │  Auth    │  │  Signals   │  │
│  │  (APIs)  │  │  (ORM)   │  │  Backends│  │  (Profile  │  │
│  │          │  │          │  │  (Email/ │  │   auto-    │  │
│  │          │  │          │  │   Google)│  │   create)  │  │
│  └──────────┘  └──────────┘  └──────────┘  └────────────┘  │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    SQLite Database                           │
│  Users, Teams, Tasks, Projects, Files, Notifications, etc.  │
└─────────────────────────────────────────────────────────────┘
```

### Directory Structure

```
FYP-TaskHive/
├── taskhive/                # Django project settings
│   ├── settings.py          # Configuration (DB, Auth, Email, OAuth)
│   ├── urls.py              # Root URL config
│   └── wsgi.py
├── core/                    # Main application
│   ├── models.py            # All data models (16 models)
│   ├── views.py             # All API views and page renderers
│   ├── urls.py              # URL routing (60+ endpoints)
│   ├── backends.py          # Custom email authentication backend
│   └── templates/core/      # HTML templates (10 pages)
│       ├── dashboard.html       # Landing page
│       ├── login_new.html       # Login/Register
│       ├── user.html            # User home (team management)
│       ├── index.html           # Workspace (main Kanban app)
│       ├── analytics.html       # Analytics dashboard
│       ├── codespace.html       # Code editor
│       ├── profile.html         # Profile settings
│       ├── public_profile.html  # Public profile view
│       └── collaboration.html   # Collaboration page
├── .env                     # Environment variables (secrets)
├── .gitignore
├── requirements.txt
└── manage.py
```

---

## 4. Pages & Features

---

### 4.1 Landing Page (Dashboard)

**URL:** `/`  
**Template:** `dashboard.html`  
**Access:** Public (no login required)

**Purpose:** First page visitors see. Introduces TaskHive and directs to login.

**Features:**
- Animated floating collaboration icons in the background
- Gradient neon branding with TaskHive logo
- Welcome hero section with tagline
- **"Get Started"** button → redirects to `/login/`
- **"Explore Workspace"** button → redirects to `/login/?next=/workspace/`
- **Feature showcase grid** (4 cards):
  - Team Sync — invite members, assign roles, real-time collaboration
  - Group Collaboration — manage multiple teams and subgroups
  - Instant Sharing — share files, updates, feedback
  - Real-time Sync — instant synchronization
- Footer with social links (Facebook, Instagram, WhatsApp)

---

### 4.2 Login / Register Page

**URL:** `/login/`  
**Template:** `login_new.html`  
**Access:** Public

**Purpose:** Unified authentication page for login, registration, and password reset.

**Features:**

#### Login Mode
- Email + Password login
- **Google Sign-In** (OAuth 2.0 popup flow via Google Identity Services)
- **Google Sign-In** (Redirect flow via `/auth/google/`)
- "Forgot password?" link → opens OTP-based reset flow
- Form validation with error messages
- Redirects to `/user/` on success (or custom `?next=` URL)

#### Register Mode
- Name + Email + Password registration
- **Email verification via OTP** — a 6-digit code is emailed to the user
- OTP verification modal before account creation
- Password minimum 6 characters
- Google Sign-Up (auto-creates account on first Google login)

#### Forgot Password Flow
1. User enters email → receives OTP via email
2. User enters OTP + new password
3. Password is reset and user can log in

**Authentication Methods:**
- Standard email/password (Django `authenticate()` with custom `EmailBackend`)
- Google OAuth 2.0 (both popup token flow and server-side redirect flow)

---

### 4.3 User Home Page

**URL:** `/user/`  
**Template:** `user.html`  
**Access:** Login required

**Purpose:** Post-login landing page for managing teams before entering a workspace.

**Features:**

#### Welcome Section
- Personalized greeting: "Welcome, [Name]"

#### "Your Teams" Dropdown
- Dropdown selector listing all teams the user belongs to
- Shows team name, code, and role badge (Admin / Member)
- **"No teams yet"** message when user has no teams
- No default or fake teams displayed on initial load

#### Team Detail View (appears after selecting a team)
- **Team info bar:** Team name, code (with copy button), role badge
- **"Go to Workspace"** button → `/workspace/<team_id>/`
- **"Edit Profile"** button → `/profile/`
- **"Leave Team"** button with confirmation dialog
- **Invite Member** panel (Admin only) — enter email to invite
- **Team Members list:**
  - Avatar initial, name, email, role badge (Admin/Member)
  - "You" badge for the current user
  - Click member → view their public profile (`/profile/<username>/`)
  - **Remove Member** button (Admin only, cannot remove self or other admins)

#### Create & Join Team (always visible)
- **Create New Team:** Enter team name → becomes team admin, receives team code
- **Join Existing Team:** Enter team code → joins as member

#### Header
- TaskHive logo (click to reset view)
- Profile link → `/profile/`
- Red Logout button

---

### 4.4 Workspace (Main App)

**URL:** `/workspace/` or `/workspace/<team_id>/`  
**Template:** `index.html`  
**Access:** Login required + Team membership required

**Purpose:** The core application where team collaboration happens.

**Layout:**
- **Header** — Logo, user info, role badge, global search, nav links, notifications, theme toggle, logout
- **Sidebar** — Tab navigation + team list
- **Main Content** — Tab-based content area

#### Sidebar Tabs
1. **Projects** — Project management
2. **Tasks** — Kanban task board
3. **Files** — File management
4. **Activity** — Activity log

#### Global Search (Ctrl+K)
- Search across tasks, projects, and files simultaneously
- Keyboard navigation (Up/Down arrows, Enter to select)
- Results grouped by type with icons
- Click result to navigate to the item

#### A. Projects Tab
- **Create New Project** — name, description, status, members
- **Project Cards** — grid layout showing:
  - Project name and description
  - Status badge (Active / Completed / Archived)
  - Task count
  - Member avatars
- **Click project** → view project detail
- **Delete project** (hover to reveal delete button)

#### B. Tasks Tab (Kanban Board)
- **Three columns:** Todo → In Progress → Done
- **Drag-and-drop** tasks between columns
- **Create New Task** with:
  - Task name and description
  - Task type: **Normal** or **Super Task** (CodeSpace-linked)
  - Project assignment (optional)
  - Priority: High (red) / Medium (yellow) / Low (green)
  - Due date
  - Assignees (Admin only — checkbox list of team members)
  - Labels (custom tags)
- **Task Cards** show:
  - Title, description, priority badge
  - Due date, assignee avatars
  - Super Task indicator (bolt icon)
  - Color-coded left border by priority
- **Click task** → opens Task Detail Modal
- **Right-click task** → context menu (Edit / Delete)

#### Task Detail Modal
- Task name, description, priority, due date, board
- **Checklist / Subtasks:**
  - Add checklist items
  - Toggle done/not done
  - Progress bar showing completion percentage
  - Delete subtask items
- **Attachments:**
  - Upload files to a task
  - View/download attached files
  - Delete attachments
- **Comments:**
  - Add comments (Ctrl+Enter to send)
  - View comment thread with author and timestamp
  - Delete comments
- **Edit** button → opens task editor

#### C. Files Tab
- **Upload files** — any file type, with upload progress bar
- **File grid** — icon based on type (PDF, Word, Excel, Image, Archive, etc.)
- **Download / Open** files
- **Delete files** (hover to reveal)
- **Context menu** on right-click

#### D. Activity Log Tab
- Chronological list of all team actions
- Color-coded icons by action type:
  - Green → Created
  - Blue → Updated
  - Red → Deleted
  - Yellow → Moved
  - Cyan → Commented
  - Purple → Attached file
- Shows actor, action, target type, timestamp
- Refresh button

#### Approvals System (Admin Only)
- Badge counter on "Approvals" button showing pending count
- Review and approve/reject member requests for:
  - Task creation, updates, deletion
  - Project changes

#### Notifications Panel
- Bell icon with unread count badge
- Dropdown panel showing all notifications
- Click notification to navigate to the relevant item
- "Mark all read" button
- Types: task assignments, comments, deadline reminders, team updates

#### Theme Toggle
- Dark mode (default) / Light mode switch
- Persisted in user profile

---

### 4.5 Analytics Page

**URL:** `/analytics/`  
**Template:** `analytics.html`  
**Access:** Login required

**Purpose:** Visual dashboard showing team productivity metrics.

**Features:**

#### Summary Cards (4 cards)
- **Total Tasks** — all tasks across boards
- **Done** — completed tasks (green)
- **In Progress** — active tasks (yellow)
- **High Priority** — urgent tasks (red)

#### Project Summary Cards (3 cards)
- Total Projects
- Active Projects
- Completed Projects

#### Charts (Chart.js)
- **Tasks by Board** — Bar chart (Todo / In Progress / Done)
- **Tasks by Priority** — Doughnut chart (High / Medium / Low)

#### Recent Tasks Table
- Last 10 tasks with name, board, priority badge, due date

---

### 4.6 CodeSpace (Code Editor)

**URL:** `/codespace/`  
**Template:** `codespace.html`  
**Access:** Login required

**Purpose:** Integrated code editor powered by Monaco Editor (the engine behind VS Code).

**Features:**

#### Monaco Editor
- Full-featured code editor with:
  - Syntax highlighting for 12+ languages (JavaScript, TypeScript, Python, HTML, CSS, JSON, C, C++, Java, Markdown, etc.)
  - Minimap
  - Auto-layout
  - VS Code dark theme

#### File Management (Sidebar)
- List of user's code files
- Click to open file in editor
- **Delete files** with confirmation
- Auto-detect language from file extension

#### Actions
- **New File** — modal to create a file with custom name/extension
- **Upload Files** — upload local files to CodeSpace
- **Save** — save current file content to the server (Ctrl+S)
- **Back** — return to workspace

#### Super Task Integration
- When a "Super Task" is clicked in the Workspace, CodeSpace opens with:
  - Pre-loaded filename from task metadata
  - Pre-filled starter code
  - Auto-create file if it doesn't exist

---

### 4.7 Profile & Settings Page

**URL:** `/profile/`  
**Template:** `profile.html`  
**Access:** Login required

**Purpose:** User's personal profile management and application settings.

**Features:**

#### Cover Photo & Avatar
- Upload/change cover photo (gradient default)
- Upload/change profile avatar
- Click camera icon to upload

#### Profile Information
- Display Name
- Username (public @username)
- Full Name
- Email
- Tagline (one-liner)
- Bio (up to 500 characters with counter)

#### Social Links
- GitHub URL
- LinkedIn URL

#### Appearance Settings
- **Theme Mode:** Dark / Light toggle
- **Accent Color:** Choose from preset color palette

#### Danger Zone
- **Delete Account** — permanently removes the account (with confirmation)

#### Actions
- **Save** — persist all changes to the server
- **Reset** — reload from server

---

### 4.8 Public Profile Page

**URL:** `/profile/<username>/`  
**Template:** `public_profile.html`  
**Access:** Login required

**Purpose:** View another team member's profile.

**Features:**
- Display name, username, tagline, bio
- Cover photo and avatar
- Social links (GitHub, LinkedIn)
- Read-only view (no editing)

---

## 5. Data Models

The application uses **16 Django models** defined in `core/models.py`:

| # | Model                   | Purpose                                          |
|---|-------------------------|--------------------------------------------------|
| 1 | **Team**                | Team entity with name, unique code, creator       |
| 2 | **TeamMembership**      | Links users to teams with roles (head/member)     |
| 3 | **Workspace**           | Workspace container per team                      |
| 4 | **Board**               | Kanban board within a workspace                   |
| 5 | **Column**              | Board column (Todo, In Progress, Done)            |
| 6 | **Task**                | Task card with title, description, priority, type |
| 7 | **Project**             | Project grouping with status tracking             |
| 8 | **ProjectFile**         | Files uploaded at team/project level              |
| 9 | **ApprovalRequest**     | Pending approval items for admin review           |
| 10 | **Notification**       | In-app notifications per user                     |
| 11 | **TaskComment**        | Comments on tasks                                 |
| 12 | **CodeFile**           | Code files in CodeSpace per user                  |
| 13 | **PasswordOTP**        | OTP records for password reset                    |
| 14 | **EmailVerificationOTP** | OTP records for email verification during signup |
| 15 | **UserProfile**        | Extended user profile (avatar, bio, theme, etc.)  |
| 16 | **ActivityLog**        | Audit trail of all team actions                   |
| 17 | **Subtask**            | Checklist items within a task                     |
| 18 | **TaskAttachment**     | File attachments on tasks                         |

### Key Relationships
- A **User** has one **UserProfile** (auto-created on signup)
- A **User** belongs to many **Teams** via **TeamMembership**
- A **Team** has many **Workspaces**, each with **Boards**, **Columns**, and **Tasks**
- A **Task** has many **Subtasks**, **TaskComments**, and **TaskAttachments**
- A **Task** can be assigned to multiple **Users** (ManyToMany)

---

## 6. API Endpoints

### Authentication APIs
| Method | Endpoint                          | Description                         |
|--------|-----------------------------------|-------------------------------------|
| POST   | `/api/login/`                     | Email/password login                |
| POST   | `/api/login/google/`              | Google OAuth token login            |
| GET    | `/auth/google/`                   | Google OAuth redirect (consent)     |
| GET    | `/auth/google/callback/`          | Google OAuth callback handler       |
| POST   | `/api/register/`                  | Register (sends OTP)                |
| POST   | `/api/register/verify/`           | Verify OTP and create account       |
| POST   | `/api/logout/`                    | Logout                              |
| GET    | `/api/me/`                        | Current user info + profile         |

### Password Reset APIs
| Method | Endpoint                          | Description                         |
|--------|-----------------------------------|-------------------------------------|
| POST   | `/api/password/request-otp/`      | Request password reset OTP          |
| POST   | `/api/password/reset/`            | Reset password with OTP             |

### Team APIs
| Method | Endpoint                          | Description                         |
|--------|-----------------------------------|-------------------------------------|
| POST   | `/api/team/create/`               | Create a new team                   |
| POST   | `/api/team/join/`                 | Join a team by code                 |
| POST   | `/api/team/invite/`               | Invite member by email              |
| POST   | `/api/team/member/remove/`        | Remove a team member                |
| GET    | `/api/team/current/`              | Get current active team             |
| GET    | `/api/my-teams/`                  | List all user's teams               |
| POST   | `/api/team/leave/`                | Leave current team                  |
| GET    | `/api/team/<id>/members/`         | List team members                   |

### Workspace / Task APIs
| Method | Endpoint                          | Description                         |
|--------|-----------------------------------|-------------------------------------|
| GET    | `/api/workspace/load/`            | Load full workspace data            |
| POST   | `/api/workspace/task/save/`       | Create or update a task             |
| POST   | `/api/workspace/task/delete/`     | Delete a task                       |
| POST   | `/api/workspace/task/move/`       | Move task between columns           |
| POST   | `/api/workspace/project/save/`    | Create or update a project          |
| POST   | `/api/workspace/project/delete/`  | Delete a project                    |
| POST   | `/api/workspace/file/upload/`     | Upload a file                       |
| POST   | `/api/workspace/file/delete/`     | Delete a file                       |
| POST   | `/api/workspace/approval/add/`    | Submit approval request             |
| POST   | `/api/workspace/approval/resolve/`| Approve or reject a request         |

### Task Detail APIs
| Method | Endpoint                                   | Description                  |
|--------|---------------------------------------------|------------------------------|
| GET    | `/api/task/<id>/comments/`                  | List task comments           |
| POST   | `/api/task/<id>/comments/add/`              | Add a comment                |
| DELETE | `/api/task/<id>/comments/<cid>/delete/`     | Delete a comment             |
| GET    | `/api/task/<id>/attachments/`               | List task attachments        |
| POST   | `/api/task/<id>/attachments/upload/`        | Upload attachment            |
| DELETE | `/api/task/<id>/attachments/<aid>/delete/`  | Delete attachment            |
| GET    | `/api/task/<id>/subtasks/`                  | List subtasks                |
| POST   | `/api/task/<id>/subtasks/save/`             | Add/update subtask           |
| DELETE | `/api/task/<id>/subtasks/<sid>/delete/`     | Delete subtask               |

### CodeSpace APIs
| Method | Endpoint                          | Description                         |
|--------|-----------------------------------|-------------------------------------|
| GET    | `/api/code/list/`                 | List user's code files              |
| GET    | `/api/code/get/<id>/`             | Get file content                    |
| POST   | `/api/code/upload/`               | Upload code file                    |
| POST   | `/api/code/save/`                 | Save file content                   |
| POST   | `/api/code/delete/`               | Delete code file                    |
| POST   | `/api/code/create/`               | Create new code file                |

### Profile APIs
| Method | Endpoint                          | Description                         |
|--------|-----------------------------------|-------------------------------------|
| GET    | `/api/profile/`                   | Get current user profile            |
| POST   | `/api/profile/save/`              | Save profile changes                |
| POST   | `/api/profile/photo/`             | Upload profile photo                |
| POST   | `/api/profile/cover/`             | Upload cover photo                  |
| POST   | `/api/profile/delete-account/`    | Delete user account                 |
| GET    | `/api/profile/public/<username>/` | Get public profile of another user  |
| POST   | `/api/profile/update/`            | Update profile fields               |
| GET    | `/api/profile/get/`               | Get profile data                    |

### Other APIs
| Method | Endpoint                               | Description                    |
|--------|----------------------------------------|--------------------------------|
| GET    | `/api/notifications/`                  | List notifications             |
| POST   | `/api/notifications/read/`             | Mark notifications as read     |
| GET    | `/api/analytics/summary/`              | Analytics data (tasks/projects)|
| POST   | `/api/notifications/deadline-reminders/`| Send deadline reminder emails |
| GET    | `/api/activity-log/`                   | Get activity log entries       |

---

## 7. User Workflow (End-to-End)

### First-Time User Flow

```
1. Visit Landing Page (/)
        │
        ▼
2. Click "Get Started" → Login Page (/login/)
        │
        ├── Register with Email
        │       │
        │       ▼
        │   Enter Name, Email, Password
        │       │
        │       ▼
        │   Receive OTP via Email
        │       │
        │       ▼
        │   Verify OTP → Account Created
        │
        ├── OR: Sign in with Google
        │       │
        │       ▼
        │   Google Consent → Auto-create Account
        │
        ▼
3. Redirected to User Home (/user/)
        │
        ▼
4. Create a New Team (enter name → receive team code)
   OR Join Existing Team (enter code)
        │
        ▼
5. Select Team from Dropdown → View Team Details
        │
        ▼
6. Click "Go to Workspace" → Workspace (/workspace/<team_id>/)
        │
        ├── Create Projects
        ├── Create Tasks (assign to members)
        ├── Drag tasks across Kanban columns
        ├── Upload files
        ├── Comment on tasks
        ├── Add subtask checklists
        ├── View activity log
        │
        ├── Navigate to Analytics → View charts & stats
        ├── Navigate to CodeSpace → Write/edit code
        ├── Navigate to Profile → Customize profile
        │
        ▼
7. Collaborate with team members in real-time
```

### Returning User Flow

```
1. Visit /login/ → Login with email/password or Google
        │
        ▼
2. Redirected to /user/ → Select team from dropdown
        │
        ▼
3. Go to Workspace → Resume work
```

---

## 8. Role-Based Access Control

### Roles

| Role       | Description                              |
|------------|------------------------------------------|
| **Head**   | Team admin/creator — full permissions     |
| **Member** | Regular team member — limited permissions |

### Permissions Matrix

| Action                     | Head (Admin) | Member |
|----------------------------|:------------:|:------:|
| Create tasks               | ✅           | ✅*    |
| Edit tasks                 | ✅           | ✅*    |
| Delete tasks               | ✅           | ✅*    |
| Move tasks (drag & drop)   | ✅           | ✅     |
| Assign tasks to members    | ✅           | ❌     |
| Create/edit/delete projects| ✅           | ✅*    |
| Upload/delete files        | ✅           | ✅     |
| Invite members             | ✅           | ❌     |
| Remove members             | ✅           | ❌     |
| View approvals             | ✅           | ❌     |
| Approve/reject requests    | ✅           | ❌     |
| Leave team                 | ✅           | ✅     |
| Comment on tasks           | ✅           | ✅     |
| Add subtasks/attachments   | ✅           | ✅     |

*\* May require approval depending on team settings*

---

## 9. Notification System

### Notification Types

| Event                    | Recipient           | Description                          |
|--------------------------|---------------------|--------------------------------------|
| Task assigned            | Assignee            | "You were assigned to [Task]"        |
| Task moved               | Assignees           | "Task moved from [Col] to [Col]"     |
| New comment              | Task participants   | "[User] commented on [Task]"         |
| Deadline approaching     | Assignees           | "Task [Name] is due in X days"       |
| Member joined team       | Team head           | "[User] joined the team"             |
| Approval request         | Team head           | "New approval request from [User]"   |
| Approval resolved        | Requester           | "Your request was approved/rejected" |

### Delivery
- **In-app:** Bell icon with unread count badge in workspace header
- **Email:** Deadline reminders sent via SMTP

---

## 10. Security Features

| Feature                      | Implementation                                    |
|------------------------------|---------------------------------------------------|
| **CSRF Protection**          | Django CSRF tokens on all POST requests            |
| **Authentication Required**  | `@login_required` decorator on protected views     |
| **Password Hashing**         | Django PBKDF2 with SHA-256 (1M iterations)         |
| **OTP Security**             | Hashed OTPs with expiration timestamps             |
| **Google OAuth 2.0**         | Server-side token verification via Google APIs     |
| **Environment Variables**    | Secrets stored in `.env` (gitignored)              |
| **Team Authorization**       | Membership checks before accessing team resources  |
| **Client Auth Guard**        | LocalStorage check redirects unauthenticated users |
| **Input Validation**         | Server-side validation on all API inputs           |
| **Account Deletion**         | Full account removal with confirmation             |

---

*Document generated for TaskHive — Final Year Project*
*Last updated: March 2026*
