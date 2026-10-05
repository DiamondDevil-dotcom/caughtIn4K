import unittest
from unittest.mock import patch
from uuid import uuid4

import verify_cloud_import as verify


class VerifyImportTests(unittest.TestCase):
    def setUp(self):
        self.account_id, self.household_id, self.gateway_id = uuid4(), uuid4(), uuid4()

    def test_matching_owner_and_gateway_pass(self):
        with (
            patch.object(verify.accounts, "login", return_value={"id": self.account_id}) as login,
            patch.object(verify.accounts, "memberships", return_value=[
                {"household_id": self.household_id, "role": "owner"},
            ]),
            patch.object(verify.gateways, "list_gateways", return_value=[
                {"gateway_id": self.gateway_id, "revoked_at": None},
            ]) as listing,
        ):
            verify.verify_owner("owner@example.com", "private-password", self.household_id, self.gateway_id)
        login.assert_called_once_with("owner@example.com", "private-password")
        listing.assert_called_once_with(self.account_id, self.household_id)

    def test_member_or_wrong_household_cannot_pass_as_owner(self):
        for member in (
            {"household_id": self.household_id, "role": "member"},
            {"household_id": uuid4(), "role": "owner"},
        ):
            with (
                patch.object(verify.accounts, "login", return_value={"id": self.account_id}),
                patch.object(verify.accounts, "memberships", return_value=[member]),
                patch.object(verify.gateways, "list_gateways") as listing,
            ):
                with self.assertRaises(ValueError):
                    verify.verify_owner("owner@example.com", "private-password", self.household_id, self.gateway_id)
            listing.assert_not_called()

    def test_missing_wrong_or_revoked_gateway_fails(self):
        for registered in (
            [], [{"gateway_id": uuid4(), "revoked_at": None}],
            [{"gateway_id": self.gateway_id, "revoked_at": "revoked"}],
        ):
            with (
                patch.object(verify.accounts, "login", return_value={"id": self.account_id}),
                patch.object(verify.accounts, "memberships", return_value=[
                    {"household_id": self.household_id, "role": "owner"},
                ]),
                patch.object(verify.gateways, "list_gateways", return_value=registered),
            ):
                with self.assertRaises(ValueError):
                    verify.verify_owner("owner@example.com", "private-password", self.household_id, self.gateway_id)


if __name__ == "__main__":
    unittest.main()
