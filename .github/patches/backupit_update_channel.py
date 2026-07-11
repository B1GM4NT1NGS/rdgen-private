#!/usr/bin/env python3
from pathlib import Path
import os
import re
import sys


MANIFEST_URL = (os.environ.get("backupitUpdateManifest") or "").strip()
CHANNEL = (os.environ.get("backupitUpdateChannel") or "").strip()
LAST_UPDATE_OPTION = "backupit-last-update-url"


def read(path):
    return Path(path).read_text(encoding="utf-8")


def write(path, text):
    Path(path).write_text(text, encoding="utf-8")


def rust_string(value):
    return value.replace("\\", "\\\\").replace('"', '\\"')


def replace_once(text, old, new, label):
    if old not in text:
        raise RuntimeError(f"Unable to patch {label}; expected source was not found")
    return text.replace(old, new, 1)


def patch_common():
    path = Path("src/common.rs")
    text = read(path)
    if "BACKUPIT_UPDATE_MANIFEST_URL" not in text:
        marker = 'const MIN_VER_MULTI_UI_SESSION: &str = "1.2.4";\n'
        constants = f'''
pub const BACKUPIT_UPDATE_MANIFEST_URL: &str = "{rust_string(MANIFEST_URL)}";
pub const BACKUPIT_UPDATE_CHANNEL: &str = "{rust_string(CHANNEL)}";
const BACKUPIT_LAST_UPDATE_OPTION: &str = "{LAST_UPDATE_OPTION}";
'''
        text = replace_once(text, marker, marker + constants, "BackupIT update constants")
    else:
        text = re.sub(
            r'pub const BACKUPIT_UPDATE_MANIFEST_URL: &str = ".*?";',
            f'pub const BACKUPIT_UPDATE_MANIFEST_URL: &str = "{rust_string(MANIFEST_URL)}";',
            text,
            count=1,
        )
        text = re.sub(
            r'pub const BACKUPIT_UPDATE_CHANNEL: &str = ".*?";',
            f'pub const BACKUPIT_UPDATE_CHANNEL: &str = "{rust_string(CHANNEL)}";',
            text,
            count=1,
        )

    old_check = '''pub fn check_software_update() {
    if is_custom_client() {
        return;
    }
    let opt = LocalConfig::get_option(keys::OPTION_ENABLE_CHECK_UPDATE);
'''
    new_check = '''pub fn check_software_update() {
    if is_custom_client() && BACKUPIT_UPDATE_MANIFEST_URL.is_empty() {
        return;
    }
    let opt = LocalConfig::get_option(keys::OPTION_ENABLE_CHECK_UPDATE);
'''
    if old_check in text:
        text = text.replace(old_check, new_check, 1)
    text = text.replace(
        "    if config::option2bool(keys::OPTION_ENABLE_CHECK_UPDATE, &opt) {\n",
        "    if !BACKUPIT_UPDATE_MANIFEST_URL.is_empty() || config::option2bool(keys::OPTION_ENABLE_CHECK_UPDATE, &opt) {\n",
        1,
    )

    marker = '''pub async fn do_check_software_update() -> hbb_common::ResultType<()> {
'''
    backupit_block = '''pub async fn do_check_software_update() -> hbb_common::ResultType<()> {
    if !BACKUPIT_UPDATE_MANIFEST_URL.is_empty() {
        let client = create_http_client_async(TlsType::Rustls, false);
        let response = client.get(BACKUPIT_UPDATE_MANIFEST_URL).send().await?;
        if !response.status().is_success() {
            *SOFTWARE_UPDATE_URL.lock().unwrap() = "".to_string();
            return Ok(());
        }
        let bytes = response.bytes().await?;
        let payload: serde_json::Value = serde_json::from_slice(&bytes)?;
        let available = payload
            .get("available")
            .and_then(|value| value.as_bool())
            .unwrap_or(false);
        let download_url = payload
            .get("download_url")
            .and_then(|value| value.as_str())
            .unwrap_or_default();
        let last_update_url = LocalConfig::get_option(BACKUPIT_LAST_UPDATE_OPTION);
        if available && !download_url.is_empty() && last_update_url != download_url {
            #[cfg(feature = "flutter")]
            {
                let mut m = HashMap::new();
                m.insert("name", "check_software_update_finish");
                m.insert("url", download_url);
                if let Ok(data) = serde_json::to_string(&m) {
                    let _ = crate::flutter::push_global_event(crate::flutter::APP_TYPE_MAIN, data);
                }
            }
            *SOFTWARE_UPDATE_URL.lock().unwrap() = download_url.to_string();
        } else {
            *SOFTWARE_UPDATE_URL.lock().unwrap() = "".to_string();
        }
        return Ok(());
    }
'''
    if "BACKUPIT_UPDATE_MANIFEST_URL.is_empty()" not in text.split(marker, 1)[-1][:3000]:
        text = replace_once(text, marker, backupit_block, "BackupIT update check")
    write(path, text)


def patch_flutter_update_trigger():
    path = Path("flutter/lib/common.dart")
    text = read(path)
    old = '''void checkUpdate() {
  if (!isWeb) {
    if (!bind.isCustomClient()) {
      platformFFI.registerEventHandler(
          kCheckSoftwareUpdateFinish, kCheckSoftwareUpdateFinish,
          (Map<String, dynamic> evt) async {
        if (evt['url'] is String) {
          stateGlobal.updateUrl.value = evt['url'];
        }
      });
      Timer(const Duration(seconds: 1), () async {
        bind.mainGetSoftwareUpdateUrl();
      });
    }
  }
}
'''
    new = '''void checkUpdate() {
  if (!isWeb) {
    platformFFI.registerEventHandler(
        kCheckSoftwareUpdateFinish, kCheckSoftwareUpdateFinish,
        (Map<String, dynamic> evt) async {
      if (evt['url'] is String) {
        stateGlobal.updateUrl.value = evt['url'];
      }
    });
    Timer(const Duration(seconds: 1), () async {
      bind.mainGetSoftwareUpdateUrl();
    });
  }
}
'''
    if old in text:
        text = text.replace(old, new, 1)
    elif "if (!bind.isCustomClient())" in text:
        raise RuntimeError(
            "Unable to enable BackupIT update startup trigger; custom-client guard changed upstream"
        )
    if "bind.mainGetSoftwareUpdateUrl();" not in text:
        raise RuntimeError("BackupIT update startup trigger is missing")
    write(path, text)


def patch_update_progress():
    path = Path("flutter/lib/desktop/widgets/update_progress.dart")
    text = read(path)
    old = '''void handleUpdate(String releasePageUrl) {
  _isExtracting.value = false;
  String downloadUrl = releasePageUrl.replaceAll('tag', 'download');
  String version = downloadUrl.substring(downloadUrl.lastIndexOf('/') + 1);
  final String downloadFile =
      bind.mainGetCommonSync(key: 'download-file-$version');
  if (downloadFile.startsWith('error:')) {
    final error = downloadFile.replaceFirst('error:', '');
    msgBox(gFFI.sessionId, 'custom-nocancel-nook-hasclose', 'Error', error,
        releasePageUrl, gFFI.dialogManager);
    return;
  }
  downloadUrl = '$downloadUrl/$downloadFile';
'''
    new = '''void handleUpdate(String releasePageUrl) {
  _isExtracting.value = false;
  final bool isBackupITUpdate = releasePageUrl.contains('/updates/download/');
  String downloadUrl = releasePageUrl;
  if (!isBackupITUpdate) {
    downloadUrl = releasePageUrl.replaceAll('tag', 'download');
    String version = downloadUrl.substring(downloadUrl.lastIndexOf('/') + 1);
    final String downloadFile =
        bind.mainGetCommonSync(key: 'download-file-$version');
    if (downloadFile.startsWith('error:')) {
      final error = downloadFile.replaceFirst('error:', '');
      msgBox(gFFI.sessionId, 'custom-nocancel-nook-hasclose', 'Error', error,
          releasePageUrl, gFFI.dialogManager);
      return;
    }
    downloadUrl = '$downloadUrl/$downloadFile';
  }
'''
    if old in text:
        text = text.replace(old, new, 1)

    old_submit = '''      onSubmit: () {
        debugPrint('Downloaded, update to new version now');
        bind.mainSetCommon(key: 'update-me', value: widget.downloadUrl);
      },
'''
    new_submit = '''      onSubmit: () {
        debugPrint('Downloaded, update to new version now');
        if (widget.releasePageUrl.contains('/updates/download/')) {
          bind.mainSetCommon(
              key: 'backupit-update-grabbed', value: widget.releasePageUrl);
        }
        bind.mainSetCommon(key: 'update-me', value: widget.downloadUrl);
      },
'''
    if old_submit in text:
        text = text.replace(old_submit, new_submit, 1)
    write(path, text)


def patch_desktop_home():
    path = Path("flutter/lib/desktop/pages/desktop_home_page.dart")
    text = read(path)
    old = '''    if (!bind.isCustomClient() &&
        updateUrl.isNotEmpty &&
        !isCardClosed &&
        bind.mainUriPrefixSync().contains('rustdesk')) {
'''
    new = '''    if (updateUrl.isNotEmpty && !isCardClosed) {
'''
    if old in text:
        text = text.replace(old, new, 1)
    text = text.replace(
        "help: isToUpdate ? 'Changelog' : null,\n          link: isToUpdate\n              ? 'https://github.com/rustdesk/rustdesk/releases/tag/${bind.mainGetNewVersion()}'\n              : null)",
        "help: isToUpdate && !updateUrl.contains('/updates/download/') ? 'Changelog' : null,\n          link: isToUpdate && !updateUrl.contains('/updates/download/')\n              ? 'https://github.com/rustdesk/rustdesk/releases/tag/${bind.mainGetNewVersion()}'\n              : null)",
    )
    write(path, text)


def patch_mobile_connection():
    path = Path("flutter/lib/mobile/pages/connection_page.dart")
    if not path.exists():
        return
    text = read(path)
    text = text.replace(
        "final url = 'https://rustdesk.com/download';",
        "final url = updateUrl.contains('/updates/download/') ? updateUrl : 'https://rustdesk.com/download';",
        1,
    )
    write(path, text)


def patch_flutter_ffi():
    path = Path("src/flutter_ffi.rs")
    text = read(path)
    marker = '''pub fn main_set_common(_key: String, _value: String) {
'''
    block = f'''pub fn main_set_common(_key: String, _value: String) {{
    if _key == "backupit-update-grabbed" {{
        hbb_common::config::LocalConfig::set_option("{LAST_UPDATE_OPTION}".to_owned(), _value);
        return;
    }}
'''
    if "backupit-update-grabbed" not in text:
        text = replace_once(text, marker, block, "BackupIT update grabbed marker")
    write(path, text)


def patch_updater():
    path = Path("src/updater.rs")
    text = read(path)
    old_arch_suffix = '''        let download_url = update_url.replace("tag", "download");
        let version = download_url.split('/').last().unwrap_or_default();
        #[cfg(target_os = "windows")]
        let download_url = if cfg!(feature = "flutter") {
            let Some(arch) = crate::platform::windows::release_arch_suffix() else {
                bail!(
                    "Unsupported Windows release architecture: {}",
                    std::env::consts::ARCH
                );
            };
            format!(
                "{}/rustdesk-{}-{}.{}",
                download_url,
                version,
                arch,
                if update_msi { "msi" } else { "exe" }
            )
        } else {
            format!("{}/rustdesk-{}-x86-sciter.exe", download_url, version)
        };
'''
    new_arch_suffix = '''        let is_backupit_direct_update = update_url.contains("/updates/download/");
        let download_base_url = if is_backupit_direct_update {
            update_url.clone()
        } else {
            update_url.replace("tag", "download")
        };
        let version = download_base_url
            .split('?')
            .next()
            .unwrap_or(&download_base_url)
            .split('/')
            .last()
            .unwrap_or_default();
        #[cfg(target_os = "windows")]
        let download_url = if is_backupit_direct_update {
            download_base_url.clone()
        } else if cfg!(feature = "flutter") {
            let Some(arch) = crate::platform::windows::release_arch_suffix() else {
                bail!(
                    "Unsupported Windows release architecture: {}",
                    std::env::consts::ARCH
                );
            };
            format!(
                "{}/rustdesk-{}-{}.{}",
                download_base_url,
                version,
                arch,
                if update_msi { "msi" } else { "exe" }
            )
        } else {
            format!("{}/rustdesk-{}-x86-sciter.exe", download_base_url, version)
        };
        #[cfg(not(target_os = "windows"))]
        let download_url = download_base_url;
'''
    old_x86_64 = '''        let download_url = update_url.replace("tag", "download");
        let version = download_url.split('/').last().unwrap_or_default();
        #[cfg(target_os = "windows")]
        let download_url = if cfg!(feature = "flutter") {
            format!(
                "{}/rustdesk-{}-x86_64.{}",
                download_url,
                version,
                if update_msi { "msi" } else { "exe" }
            )
        } else {
            format!("{}/rustdesk-{}-x86-sciter.exe", download_url, version)
        };
'''
    new_x86_64 = '''        let is_backupit_direct_update = update_url.contains("/updates/download/");
        let download_base_url = if is_backupit_direct_update {
            update_url.clone()
        } else {
            update_url.replace("tag", "download")
        };
        let version = download_base_url
            .split('?')
            .next()
            .unwrap_or(&download_base_url)
            .split('/')
            .last()
            .unwrap_or_default();
        #[cfg(target_os = "windows")]
        let download_url = if is_backupit_direct_update {
            download_base_url.clone()
        } else if cfg!(feature = "flutter") {
            format!(
                "{}/rustdesk-{}-x86_64.{}",
                download_base_url,
                version,
                if update_msi { "msi" } else { "exe" }
            )
        } else {
            format!("{}/rustdesk-{}-x86-sciter.exe", download_base_url, version)
        };
        #[cfg(not(target_os = "windows"))]
        let download_url = download_base_url;
'''
    patched_download = "let is_backupit_direct_update = update_url.contains" in text
    if not patched_download and old_arch_suffix in text:
        text = text.replace(old_arch_suffix, new_arch_suffix, 1)
        patched_download = True
    if not patched_download and old_x86_64 in text:
        text = text.replace(old_x86_64, new_x86_64, 1)
        patched_download = True
    if not patched_download:
        raise RuntimeError("Unable to patch BackupIT updater download block; expected source was not found")

    marker = '''        if has_no_active_conns() {
            #[cfg(target_os = "windows")]
            update_new_version(update_msi, &version, &file_path);
        }
'''
    replacement = f'''        if has_no_active_conns() {{
            if is_backupit_direct_update {{
                hbb_common::config::LocalConfig::set_option("{LAST_UPDATE_OPTION}".to_owned(), update_url.clone());
            }}
            #[cfg(target_os = "windows")]
            update_new_version(update_msi, &version, &file_path);
        }}
'''
    if marker in text and LAST_UPDATE_OPTION not in text:
        text = text.replace(marker, replacement, 1)
    write(path, text)


def main():
    if not MANIFEST_URL:
        print("BackupIT update channel patch skipped: no backupitUpdateManifest env value")
        return 0
    patch_common()
    patch_flutter_update_trigger()
    patch_update_progress()
    patch_desktop_home()
    patch_mobile_connection()
    patch_flutter_ffi()
    patch_updater()
    print(f"BackupIT update channel enabled: {CHANNEL} -> {MANIFEST_URL}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
