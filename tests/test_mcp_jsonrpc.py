import unittest

from huicode.mcp.jsonrpc import JSONRPCError, JSONRPCPeer, MCPProtocolError, validate_response


class MCPJSONRPCTests(unittest.TestCase):
    def test_request_ids_increment_and_notifications_have_no_id(self) -> None:
        peer = JSONRPCPeer()

        first = peer.request("tools/list")
        second = peer.request("tools/call", {"name": "echo"})
        notification = peer.notification("notifications/initialized")

        self.assertEqual(first["id"], 1)
        self.assertEqual(second["id"], 2)
        self.assertNotIn("id", notification)

    def test_validate_success_and_id_mismatch(self) -> None:
        result = validate_response({"jsonrpc": "2.0", "id": 7, "result": {"ok": True}}, 7)

        self.assertEqual(result, {"ok": True})
        with self.assertRaisesRegex(MCPProtocolError, "id"):
            validate_response({"jsonrpc": "2.0", "id": 8, "result": {}}, 7)

    def test_error_response_raises_jsonrpc_error(self) -> None:
        with self.assertRaises(JSONRPCError) as caught:
            validate_response(
                {"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "missing"}},
                1,
            )

        self.assertEqual(caught.exception.code, -32601)
        self.assertIn("missing", str(caught.exception))

    def test_invalid_envelope_is_error(self) -> None:
        with self.assertRaises(MCPProtocolError):
            validate_response({"id": 1, "result": {}}, 1)


if __name__ == "__main__":
    unittest.main()
