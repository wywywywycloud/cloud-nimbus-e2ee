import sys

from django.test import RequestFactory, SimpleTestCase, override_settings
from django.views.debug import get_exception_reporter_filter
from django.views.decorators.debug import sensitive_variables

from core.debug import NimbusExceptionReporterFilter


@sensitive_variables()
def _protocol_failure():
    protocol_state = "synthetic-protocol-state-for-redaction-test"
    raise RuntimeError("Protocol processing failed")


class ErrorReportRedactionTests(SimpleTestCase):
    def test_setup_and_bridge_location_are_redacted_in_both_debug_modes(self):
        for debug in (True, False):
            with self.subTest(debug=debug), override_settings(
                DEBUG=debug,
                OPAQUE_SERVER_SETUP="synthetic-setup-for-redaction-test",
                OPAQUE_MODULE_PATH="/private/synthetic/opaque.js",
            ):
                request = RequestFactory().get("/api/opaque/session/")
                request.META["OPAQUE_SERVER_SETUP"] = "synthetic-environment-setup"
                reporter_filter = get_exception_reporter_filter(request)
                self.assertIsInstance(reporter_filter, NimbusExceptionReporterFilter)
                safe = reporter_filter.get_safe_settings()
                for key in ("OPAQUE_SERVER_SETUP", "OPAQUE_MODULE_PATH"):
                    self.assertEqual(safe[key], reporter_filter.cleansed_substitute)
                self.assertEqual(
                    reporter_filter.get_safe_request_meta(request)["OPAQUE_SERVER_SETUP"],
                    reporter_filter.cleansed_substitute,
                )

    @override_settings(DEBUG=True)
    def test_protocol_local_variables_remain_redacted_in_debug_tracebacks(self):
        request = RequestFactory().get("/api/opaque/session/")
        reporter_filter = get_exception_reporter_filter(request)
        try:
            _protocol_failure()
        except RuntimeError:
            traceback = sys.exc_info()[2]
        while traceback.tb_next is not None:
            traceback = traceback.tb_next
        variables = dict(reporter_filter.get_traceback_frame_variables(request, traceback.tb_frame))
        self.assertEqual(variables["protocol_state"], reporter_filter.cleansed_substitute)
