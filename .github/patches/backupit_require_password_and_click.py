#!/usr/bin/env python3
"""Make BackupIT's Ask & Pass builds require both authentication steps."""

import os
import sys
from pathlib import Path


def replace_once(text, old, new, label):
    if old not in text:
        raise RuntimeError(f"Unable to patch {label}; expected RustDesk source was not found")
    return text.replace(old, new, 1)


def main():
    enabled = os.environ.get("backupitRequirePasswordAndClick", "").strip().lower()
    if enabled != "true":
        print("BackupIT Ask & Pass patch skipped")
        return 0

    root = Path(os.environ.get("BACKUPIT_SOURCE_ROOT", "."))
    path = root / "src" / "server" / "connection.rs"
    text = path.read_text(encoding="utf-8")

    connection_state = '''    tx_to_cm: mpsc::UnboundedSender<ipc::Data>,
    authorized: bool,
    require_2fa: Option<totp_rs::TOTP>,'''
    connection_state_patched = '''    tx_to_cm: mpsc::UnboundedSender<ipc::Data>,
    authorized: bool,
    // Ask & Pass has two independent requirements. Neither one may start
    // the desktop session until the other has completed.
    backupit_password_prompted: bool,
    backupit_password_verified: bool,
    backupit_remote_approved: bool,
    require_2fa: Option<totp_rs::TOTP>,'''
    text = replace_once(text, connection_state, connection_state_patched, "Ask & Pass connection state")

    connection_state_init = '''            tx_to_cm,
            authorized: false,
            keyboard: Self::permission(keys::OPTION_ENABLE_KEYBOARD, &control_permissions),'''
    connection_state_init_patched = '''            tx_to_cm,
            authorized: false,
            backupit_password_prompted: false,
            backupit_password_verified: false,
            backupit_remote_approved: false,
            keyboard: Self::permission(keys::OPTION_ENABLE_KEYBOARD, &control_permissions),'''
    text = replace_once(
        text,
        connection_state_init,
        connection_state_init_patched,
        "Ask & Pass connection-state initialization",
    )

    authorize = '''                        ipc::Data::Authorize => {
                            conn.set_conn_audit_primary_auth(ConnAuditPrimaryAuth::Click);
                            conn.require_2fa.take();
                            if !conn.send_logon_response_and_keep_alive().await {
                                break;
                            }
                            if conn.port_forward_socket.is_some() {
                                break;
                            }
                        }'''
    authorize_gated = '''                        ipc::Data::Authorize => {
                            conn.backupit_remote_approved = true;
                            if !conn.backupit_password_verified {
                                // The user may approve first, but the controller still has to
                                // supply the permanent password before this session can start.
                                continue;
                            }
                            conn.set_conn_audit_primary_auth(ConnAuditPrimaryAuth::Click);
                            conn.require_2fa.take();
                            if !conn.send_logon_response_and_keep_alive().await {
                                break;
                            }
                            if conn.port_forward_socket.is_some() {
                                break;
                            }
                        }'''
    text = replace_once(text, authorize, authorize_gated, "Ask & Pass remote approval gate")

    gate = '''            if (password::approve_mode() == ApproveMode::Click && !allow_logon_screen_password)
                || password::approve_mode() == ApproveMode::Both && !password::has_valid_password()
            {'''
    gated = '''            // BackupIT Ask & Pass requires the controller's password and the
            // controlled user's explicit approval for every new connection.
            let backupit_require_password_and_click = true;

            if backupit_require_password_and_click && !self.backupit_password_prompted {
                // Ignore any automatic/cached credential for the first request so the
                // controller is always asked to type the password. Start the connection
                // manager at the same time so the controlled user sees Allow/Dismiss.
                self.backupit_password_prompted = true;
                self.try_start_cm(lr.my_id, lr.my_name, false);
                self.send_login_error(crate::client::LOGIN_MSG_PASSWORD_EMPTY)
                    .await;
                return true;
            } else if (password::approve_mode() == ApproveMode::Click && !allow_logon_screen_password)
                || (password::approve_mode() == ApproveMode::Both
                    && !password::has_valid_password()
                    && !backupit_require_password_and_click)
            {'''
    text = replace_once(text, gate, gated, "Ask & Pass approval gate")

    recent_session = '''            } else if self.is_recent_session(false) {'''
    recent_session_gated = '''            } else if self.is_recent_session(false)
                && !backupit_require_password_and_click
            {'''
    text = replace_once(text, recent_session, recent_session_gated, "Ask & Pass session reuse")

    empty_password = '''            } else if lr.password.is_empty() {
                if err_msg.is_empty() {'''
    empty_password_gated = '''            } else if lr.password.is_empty() {
                if backupit_require_password_and_click {
                    self.send_login_error(crate::client::LOGIN_MSG_PASSWORD_EMPTY)
                        .await;
                } else if err_msg.is_empty() {'''
    text = replace_once(text, empty_password, empty_password_gated, "Ask & Pass password gate")

    authorized = '''                    self.update_failure_with_scope(failure, true, 0, FailureScope::Default);
                    if err_msg.is_empty() {
                        #[cfg(target_os = "linux")]
                        self.linux_headless_handle.wait_desktop_cm_ready().await;
                        if !self.send_logon_response_and_keep_alive().await {
                            return false;
                        }
                        self.try_start_cm(lr.my_id, lr.my_name, self.authorized);
                    } else {'''
    authorization_wait = '''                    self.update_failure_with_scope(failure, true, 0, FailureScope::Default);
                    if err_msg.is_empty() && backupit_require_password_and_click {
                        self.backupit_password_verified = true;
                        if self.backupit_remote_approved {
                            if !self.send_logon_response_and_keep_alive().await {
                                return false;
                            }
                        } else {
                            self.send_login_error(crate::client::LOGIN_MSG_NO_PASSWORD_ACCESS)
                                .await;
                        }
                    } else if err_msg.is_empty() {
                        #[cfg(target_os = "linux")]
                        self.linux_headless_handle.wait_desktop_cm_ready().await;
                        if !self.send_logon_response_and_keep_alive().await {
                            return false;
                        }
                        self.try_start_cm(lr.my_id, lr.my_name, self.authorized);
                    } else {'''
    text = replace_once(text, authorized, authorization_wait, "Ask & Pass approval wait")

    cm_path = root / "src" / "ui" / "cm.tis"
    cm_text = cm_path.read_text(encoding="utf-8")
    cm_text = replace_once(
        cm_text,
        "        var show_accept_btn = handler.get_option('approve-mode') != 'password';",
        "        // Ask & Pass must still show Allow if an older setting is preserved during an update.\n"
        "        var show_accept_btn = true;",
        "Ask & Pass connection-manager controls",
    )

    path.write_text(text, encoding="utf-8")
    cm_path.write_text(cm_text, encoding="utf-8")
    print("BackupIT Ask & Pass patch enabled")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"BackupIT Ask & Pass patch failed: {exc}", file=sys.stderr)
        sys.exit(1)
