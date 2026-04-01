# from django.urls import path
# from . import views

# urlpatterns = [
#     # Public landing
#     path("", views.dashboard_page, name="dashboard"),

#     # Auth
#     path("login/", views.login_page, name="login"),
#     path("logout/", views.api_logout, name="logout"),

#     # After login: user setup page
#     path("user/", views.user_page, name="user"),

#     # Protected app pages
#     path("workspace/", views.workspace, name="workspace"),   # index.html
#     path("analytics/", views.analytics_page, name="analytics"),
#     path("codespace/", views.codespace_page, name="codespace"),
#     path("profile/", views.profile_page, name="profile"),

#     # APIs
#     path("api/login/", views.api_login, name="api_login"),
#     path("api/register/", views.api_register, name="api_register"),
#     path("api/me/", views.api_me, name="api_me"),
    
#     path("api/code/upload/", views.api_code_upload, name="api_code_upload"),
#     path("api/code/save/", views.api_code_save, name="api_code_save"),
    
#     path("api/code/list/", views.api_code_list, name="api_code_list"),
#     path("api/code/get/<int:file_id>/", views.api_code_get, name="api_code_get"),
#     path("api/code/upload/", views.api_code_upload, name="api_code_upload"),
#     path("api/code/save/", views.api_code_save, name="api_code_save"),
#     path("api/password/request-otp/", views.api_password_request_otp, name="api_password_request_otp"),
#     path("api/password/reset/", views.api_password_reset, name="api_password_reset"),
    
#      path("api/me/", views.api_me, name="api_me"),
#     path("api/profile/update/", views.api_profile_update, name="api_profile_update"),

#     path("api/login/", views.api_login, name="api_login"),
#     path("api/register/", views.api_register, name="api_register"),
#     path("api/logout/", views.api_logout, name="api_logout"),

# ]




from django.urls import path
from . import views

urlpatterns = [
    # --------------------
    # Health check
    # --------------------
    path("api/health/", views.api_health, name="api_health"),

    # --------------------
    # Public landing
    # --------------------
    path("", views.dashboard_page, name="dashboard"),

    # --------------------
    # Pages
    # --------------------
    path("login/", views.login_page, name="login"),
    path("user/", views.user_page, name="user"),                 # after login
    path("workspace/", views.workspace, name="workspace"),       # index.html (main app)
    path("workspace/<int:team_id>/", views.workspace_team, name="workspace_team"),
    path("analytics/", views.analytics_page, name="analytics"),
    path("codespace/", views.codespace_page, name="codespace"),
    path("profile/", views.profile_page, name="profile"),
    path("profile/<str:username>/", views.public_profile_page, name="public_profile"),

    # --------------------
    # Auth APIs
    # --------------------
    path("api/login/", views.api_login, name="api_login"),
    path("api/login/google/", views.api_login_google, name="api_login_google"),
    path("auth/google/", views.google_auth_redirect, name="google_auth_redirect"),
    path("auth/google/callback/", views.google_auth_callback, name="google_auth_callback"),
    path("api/register/", views.api_register, name="api_register"),
    path("api/register/verify/", views.api_register_verify, name="api_register_verify"),
    path("api/logout/", views.api_logout, name="api_logout"),
    path("api/me/", views.api_me, name="api_me"),

    # --------------------
    # Team APIs
    # --------------------
    path("api/team/create/", views.api_team_create, name="api_team_create"),
    path("api/team/join/", views.api_team_join, name="api_team_join"),
    path("api/team/invite/", views.api_team_invite, name="api_team_invite"),
    path("api/team/member/remove/", views.api_team_member_remove, name="api_team_member_remove"),
    path("api/team/current/", views.api_team_current, name="api_team_current"),
    path("api/my-teams/", views.api_my_teams, name="api_my_teams"),
    path("api/team/leave/", views.api_team_leave, name="api_team_leave"),
    path("api/team/<int:team_id>/members/", views.api_team_members, name="api_team_members"),

    # --------------------
    # CodeSpace APIs
    # --------------------
    path("api/code/list/", views.api_code_list, name="api_code_list"),
    path("api/code/get/<int:file_id>/", views.api_code_get, name="api_code_get"),
    path("api/code/upload/", views.api_code_upload, name="api_code_upload"),
    path("api/code/save/", views.api_code_save, name="api_code_save"),
    path("api/code/delete/", views.api_code_delete, name="api_code_delete"),

    # --------------------
    # Password Reset APIs (OTP)
    # --------------------
    path("api/password/request-otp/", views.api_password_request_otp, name="api_password_request_otp"),
    path("api/password/reset/", views.api_password_reset, name="api_password_reset"),

    # --------------------
    # Profile APIs
    # --------------------
    path("api/profile/", views.api_profile, name="api_profile"),
    path("api/profile/save/", views.api_profile_save, name="api_profile_save"),
    path("api/profile/photo/", views.api_profile_photo, name="api_profile_photo"),
    path("api/profile/cover/", views.api_profile_cover, name="api_profile_cover"),
    path("api/profile/delete-account/", views.api_profile_delete_account, name="api_profile_delete_account"),
    path("api/profile/public/<str:username>/", views.api_profile_public, name="api_profile_public"),
    path("api/profile/update/", views.api_profile_update, name="api_profile_update"),
    path("api/profile/get/", views.api_profile_get, name="api_profile_get"),
    path("api/code/create/", views.api_code_create, name="api_code_create"),

    # --------------------
    # Workspace Data APIs (DB-backed)
    # --------------------
    path("api/workspace/load/", views.api_workspace_load, name="api_workspace_load"),
    path("api/workspace/task/save/", views.api_workspace_task_save, name="api_workspace_task_save"),
    path("api/workspace/task/delete/", views.api_workspace_task_delete, name="api_workspace_task_delete"),
    path("api/workspace/task/move/", views.api_workspace_task_move, name="api_workspace_task_move"),
    path("api/workspace/project/save/", views.api_workspace_project_save, name="api_workspace_project_save"),
    path("api/workspace/project/delete/", views.api_workspace_project_delete, name="api_workspace_project_delete"),
    path("api/workspace/file/upload/", views.api_workspace_file_upload, name="api_workspace_file_upload"),
    path("api/workspace/file/delete/", views.api_workspace_file_delete, name="api_workspace_file_delete"),
    path("api/workspace/approval/add/", views.api_workspace_approval_add, name="api_workspace_approval_add"),
    path("api/workspace/approval/resolve/", views.api_workspace_approval_resolve, name="api_workspace_approval_resolve"),
    path("api/notifications/", views.api_notifications_list, name="api_notifications_list"),
    path("api/notifications/read/", views.api_notifications_read, name="api_notifications_read"),
    path("api/analytics/summary/", views.api_analytics_summary, name="api_analytics_summary"),
    path("api/notifications/deadline-reminders/", views.api_send_deadline_reminders, name="api_send_deadline_reminders"),

    # --------------------
    # Activity Log API
    # --------------------
    path("api/activity-log/", views.api_activity_log, name="api_activity_log"),

    # --------------------
    # Task Comments API
    # --------------------
    path("api/task/<int:task_id>/comments/", views.api_task_comments, name="api_task_comments"),
    path("api/task/<int:task_id>/comments/add/", views.api_task_comment_add, name="api_task_comment_add"),
    path("api/task/<int:task_id>/comments/<int:comment_id>/delete/", views.api_task_comment_delete, name="api_task_comment_delete"),

    # --------------------
    # Task Attachments API
    # --------------------
    path("api/task/<int:task_id>/attachments/", views.api_task_attachments, name="api_task_attachments"),
    path("api/task/<int:task_id>/attachments/upload/", views.api_task_attachment_upload, name="api_task_attachment_upload"),
    path("api/task/<int:task_id>/attachments/<int:attachment_id>/delete/", views.api_task_attachment_delete, name="api_task_attachment_delete"),

    # --------------------
    # Subtasks / Checklists API
    # --------------------
    path("api/task/<int:task_id>/subtasks/", views.api_task_subtasks, name="api_task_subtasks"),
    path("api/task/<int:task_id>/subtasks/save/", views.api_task_subtask_save, name="api_task_subtask_save"),
    path("api/task/<int:task_id>/subtasks/<int:subtask_id>/delete/", views.api_task_subtask_delete, name="api_task_subtask_delete"),
]
