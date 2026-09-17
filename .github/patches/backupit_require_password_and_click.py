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

    gate = '''            if (password::approve_mode() == ApproveMode::Click && !allow_logon_screen_password)
                || password::approve_mode() == ApproveMode::Both && !password::has_valid_password()
            {'''
    gated = '''            // BackupIT Ask & Pass requires the controller's password and the
            // controlled user's explicit approval for every new connection.
            let backupit_require_password_and_click = true;

            if (password::approve_mode() == ApproveMode::Click && !allow_logon_screen_password)
                || (password::approve_mode() == ApproveMode::Both
                    && !password::has_valid_password()
                    && !backupit_require_password_and_click)
            {'''
    text = replace_once(text, gate, gated, "Ask & Pass approval gate")

    recent_session = '''            } else if self.is_recent_session(false) {'''
    recent_session_gated = '''            } else if self.is_recent_session(false)
                && !(backupit_require_password_and_click
                    && password::approve_mode() == ApproveMode::Both)
            {'''
    text = replace_once(text, recent_session, recent_session_gated, "Ask & Pass session reuse")

    empty_password = '''            } else if lr.password.is_empty() {
                if err_msg.is_empty() {'''
    empty_password_gated = '''            } else if lr.password.is_empty() {
                if backupit_require_password_and_click
                    && password::approve_mode() == ApproveMode::Both
                {
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
                    if err_msg.is_empty()
                        && backupit_require_password_and_click
                        && password::approve_mode() == ApproveMode::Both
                    {
                        self.try_start_cm(lr.my_id, lr.my_name, false);
                        self.send_login_error(crate::client::LOGIN_MSG_NO_PASSWORD_ACCESS)
                            .await;
                    } else if err_msg.is_empty() {
                        #[cfg(target_os = "linux")]
                        self.linux_headless_handle.wait_desktop_cm_ready().await;
                        if !self.send_logon_response_and_keep_alive().await {
                            return false;
                        }
                        self.try_start_cm(lr.my_id, lr.my_name, self.authorized);
                    } else {'''
    text = replace_once(text, authorized, authorization_wait, "Ask & Pass approval wait")

    path.write_text(text, encoding="utf-8")
    print("BackupIT Ask & Pass patch enabled")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"BackupIT Ask & Pass patch failed: {exc}", file=sys.stderr)
        sys.exit(1)
