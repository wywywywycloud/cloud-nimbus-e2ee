"""Block obsolete auth and constrain incomplete accounts to onboarding."""
from django.http import JsonResponse
from django.shortcuts import redirect


class BrowserAuthBoundaryMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        legacy = request.path in {
            '/auth/login/', '/auth/register/', '/auth/login/code/', '/auth/login/code/resend/',
            '/auth/verify-email/', '/auth/verify-email/resend/', '/auth/remind-username/', '/auth/delete-account/',
        } or request.path.startswith(('/auth/password-reset/', '/auth/recover-account/'))
        if legacy:
            if request.method in {'GET', 'HEAD'}:
                return redirect('/vault/')
            return JsonResponse({'error': 'use_opaque_or_passkey', 'client': '/vault/'}, status=410)
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        from accounts.onboarding import state, valid, full_access
        if not request.user.is_authenticated:
            return None
        gates = state(request.user)
        reset = request.session.get('password_setup_required', False)
        path = request.path
        public = path.startswith(('/vault/', '/static/', '/api/opaque/login/', '/api/passkeys/login/', '/api/passkeys/reset/', '/api/otp/login/')) or path in {'/auth/logout/', '/api/cypher/session/', '/auth/telegram/webhook/'}
        if public:
            return None
        if not gates['onboarding_required'] and not reset:
            if full_access(request):
                return None
            return JsonResponse({'error': 'authentication_required'}, status=401)
        if not valid(request):
            return JsonResponse({'error': 'onboarding_expired'}, status=401)
        allowed = {'/api/opaque/change/start/', '/api/opaque/change/finish/'} if reset else {
            'telegram': {'/auth/telegram/link/', '/auth/telegram/status/'},
            'passkey': {'/api/cypher/passkey/skip/', '/api/cypher/vault/', '/api/passkeys/register/start/', '/api/passkeys/register/finish/', '/api/passkeys/activate/start/', '/api/passkeys/activate/finish/', '/auth/telegram/status/'},
            'totp': {'/api/otp/setup/start/', '/api/otp/setup/finish/'},
        }.get(gates['next_step'], set())
        allowed |= {'/api/opaque/change/start/', '/api/opaque/change/finish/'}
        if path not in allowed:
            return JsonResponse({'error': 'onboarding_required', 'next_step': 'password' if reset else gates['next_step']}, status=403)
        return None
