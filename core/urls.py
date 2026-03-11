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
    # Public landing
    # --------------------
    path("", views.dashboard_page, name="dashboard"),

    # --------------------
    # Pages
    # --------------------
    path("login/", views.login_page, name="login"),
    path("user/", views.user_page, name="user"),                 # after login
    path("workspace/", views.workspace, name="workspace"),       # index.html (main app)
    path("analytics/", views.analytics_page, name="analytics"),
    path("codespace/", views.codespace_page, name="codespace"),
    path("profile/", views.profile_page, name="profile"),

    # --------------------
    # Auth APIs
    # --------------------
    path("api/login/", views.api_login, name="api_login"),
    path("api/register/", views.api_register, name="api_register"),
    path("api/logout/", views.api_logout, name="api_logout"),
    path("api/me/", views.api_me, name="api_me"),

    # --------------------
    # CodeSpace APIs
    # --------------------
    path("api/code/list/", views.api_code_list, name="api_code_list"),
    path("api/code/get/<int:file_id>/", views.api_code_get, name="api_code_get"),
    path("api/code/upload/", views.api_code_upload, name="api_code_upload"),
    path("api/code/save/", views.api_code_save, name="api_code_save"),

    # --------------------
    # Password Reset APIs (OTP)
    # --------------------
    path("api/password/request-otp/", views.api_password_request_otp, name="api_password_request_otp"),
    path("api/password/reset/", views.api_password_reset, name="api_password_reset"),

    # --------------------
    # Profile APIs
    # --------------------
    path("api/profile/update/", views.api_profile_update, name="api_profile_update"),
    path("api/profile/get/", views.api_profile_get, name="api_profile_get"),
]
