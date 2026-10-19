"""Exercise real PKCE and tenant claims against a disposable Compose installation."""
import argparse
import base64
import hashlib
import secrets
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx


class LoginForm(HTMLParser):
    action = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "form" and attributes.get("id") == "kc-form-login":
            self.action = attributes.get("action")


def checked(response):
    response.raise_for_status()
    return response.json() if response.content else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", required=True)
    parser.add_argument("--allow-self-signed", action="store_true")
    args = parser.parse_args()
    origin = args.origin.rstrip("/")
    environment = dict(line.split("=", 1) for line in Path(".env").read_text().splitlines() if "=" in line)
    realm_path = "/admin/realms/pcmed"
    password = secrets.token_urlsafe(32)
    with httpx.Client(base_url=origin, verify=not args.allow_self_signed, trust_env=False, timeout=30) as client:
        token = checked(client.post("/realms/master/protocol/openid-connect/token", data={
            "grant_type": "password", "client_id": "admin-cli", "username": "bootstrap-admin", "password": environment["KEYCLOAK_ADMIN_PASSWORD"]}))
        administrator = {"Authorization": "Bearer " + token["access_token"]}

        def create_user(username, role):
            response = client.post(realm_path + "/users", headers=administrator, json={
                "username": username, "enabled": True, "email": username + "@example.invalid", "emailVerified": True,
                "firstName": "CI", "lastName": "Tester", "credentials": [{"type": "password", "value": password, "temporary": False}]})
            checked(response)
            user_id = response.headers["Location"].rsplit("/", 1)[1]
            role_data = checked(client.get(realm_path + "/roles/" + role, headers=administrator))
            checked(client.post(realm_path + f"/users/{user_id}/role-mappings/realm", headers=administrator, json=[role_data]))
            return user_id

        def login(username):
            verifier = secrets.token_urlsafe(48)
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            state = secrets.token_urlsafe(24)
            client.cookies.clear()
            response = client.get("/realms/pcmed/protocol/openid-connect/auth?" + urlencode({
                "client_id": "pcmed-console", "redirect_uri": origin + "/", "response_type": "code", "scope": "openid profile email",
                "code_challenge_method": "S256", "code_challenge": challenge, "state": state, "nonce": secrets.token_urlsafe(24)}))
            response.raise_for_status()
            form = LoginForm()
            form.feed(response.text)
            assert form.action and urlsplit(form.action).netloc == urlsplit(origin).netloc, "Unexpected login form origin"
            submitted = client.post(form.action, data={"username": username, "password": password, "credentialId": ""})
            assert submitted.status_code in {302, 303}, "Password-only login must succeed when OTP is not configured"
            location = submitted.headers["Location"]
            assert urlsplit(location).netloc == urlsplit(origin).netloc
            query = parse_qs(urlsplit(location).query)
            assert query.get("state") == [state]
            tokens = checked(client.post("/realms/pcmed/protocol/openid-connect/token", data={
                "grant_type": "authorization_code", "client_id": "pcmed-console", "redirect_uri": origin + "/",
                "code": query["code"][0], "code_verifier": verifier}))
            return {"Authorization": "Bearer " + tokens["access_token"]}

        suffix = secrets.token_hex(4)
        admin_username, operator_username = "ci-admin-" + suffix, "ci-operator-" + suffix
        create_user(admin_username, "platform_admin")
        operator_id = create_user(operator_username, "operator")
        admin_headers = login(admin_username)
        assert "platform_admin" in checked(client.get("/api/me", headers=admin_headers))["roles"]
        alpha = checked(client.post("/api/tenants", headers=admin_headers, json={"name": "CI Alpha " + suffix}))
        beta = checked(client.post("/api/tenants", headers=admin_headers, json={"name": "CI Beta " + suffix}))
        group_response = client.post(realm_path + "/groups", headers=administrator, json={"name": alpha["id"]})
        checked(group_response)
        group_id = group_response.headers["Location"].rsplit("/", 1)[1]
        checked(client.put(realm_path + f"/users/{operator_id}/groups/{group_id}", headers=administrator))
        operator_headers = login(operator_username)
        profile = checked(client.get("/api/me", headers=operator_headers))
        assert profile["tenant_ids"] == [alpha["id"]]
        assert checked(client.get("/api/tenants", headers=operator_headers)) == [alpha]
        assert client.get(f"/api/tenants/{beta['id']}/devices", headers=operator_headers).status_code == 403
        assert client.post(f"/api/tenants/{alpha['id']}/enrollments", headers=operator_headers).status_code == 201
    print("OIDC PKCE, optional MFA, audience/role/group claims and client isolation passed.")


if __name__ == "__main__":
    main()
