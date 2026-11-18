"""Integrate the private feed into a local RustDesk 1.5.3 pilot source tree."""

import base64
import json
import os
from pathlib import Path
import re


FIXTURE_KEY = "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"


def validate_branded_pilot(encoded):
    config = json.loads(base64.b64decode(encoded, validate=True))
    if not isinstance(config, dict) or not config.get("app-name"):
        raise ValueError("Branded pilot needs a named custom configuration")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", config["app-name"]):
        raise ValueError("Windows pilot app name may contain only letters, numbers, hyphens and underscores")
    if config.get("password"):
        raise ValueError("A branded updater pilot must not embed a connection password")


def replace(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f"Unsupported RustDesk source: expected one {old.splitlines()[0]!r}")
    return text.replace(old, new, 1)


def patch(root, endpoint, channel, public_key, build_id="", runtime_endpoint=False, installed_version=""):
    if not re.fullmatch(r"https://backupit\.co\.uk/[a-f0-9]{24}/index\.php", endpoint):
        raise ValueError("Invalid pilot update endpoint")
    if channel not in {"windows", "windows-admin", "windows-x86", "windows-ask-only", "windows-ask-pass", "macos"}:
        raise ValueError("Pilot does not support this client platform")
    if not re.fullmatch(r"[a-f0-9]{64}", public_key):
        raise ValueError("Expected a 32-byte Ed25519 public key in hex")
    if runtime_endpoint and public_key in {FIXTURE_KEY, "0" * 64}:
        raise ValueError("A real pilot verification key is required for a runtime endpoint")
    if build_id and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,160}", build_id):
        raise ValueError("Invalid pilot build ID")
    if installed_version and not re.fullmatch(r"BackupIT-\d{4}\.\d{2}\.\d{2}\.\d{1,9}", installed_version):
        raise ValueError("Invalid installed pilot version")
    changes = {}

    def edit(path, old, new):
        target = root / path
        changes[target] = replace(changes[target] if target in changes else target.read_text(encoding="utf-8"), old, new)

    key = ", ".join(str(n) for n in bytes.fromhex(public_key))
    adapter = f'''

pub(crate) const ENDPOINT: &str = "{endpoint}";
const CHANNEL: &str = "{channel}";
const PUBLIC_KEY: [u8; 32] = [{key}];
const BUILD_ID: &str = "{build_id}";
const INSTALLED_VERSION: &str = "{installed_version}";
const RUNTIME_ENDPOINT: bool = {str(runtime_endpoint).lower()};

pub(crate) fn pilot_endpoint() -> String {{
    if RUNTIME_ENDPOINT {{
        if let Ok(endpoint) = std::env::var("BACKUPIT_PILOT_RUNTIME_ENDPOINT") {{
            if endpoint.strip_prefix(ORIGIN).and_then(|url| url.strip_suffix("/index.php"))
                .is_some_and(|directory| lower_hex(directory, 24)) {{
                return endpoint;
            }}
        }}
    }}
    ENDPOINT.to_owned()
}}

pub(crate) fn pilot_latest(format: &str) -> ResultType<Option<Release>> {{
    let token = std::env::var("BACKUPIT_PILOT_TOKEN")?;
    let installed = if INSTALLED_VERSION.is_empty() {{
        std::env::var("BACKUPIT_PILOT_INSTALLED_VERSION")?
    }} else {{
        INSTALLED_VERSION.to_owned()
    }};
    let endpoint = pilot_endpoint();
    let release = PrivateFeed::new(&endpoint, CHANNEL, &token)?.latest(PUBLIC_KEY, format, &installed)?;
    Ok(release.filter(|value| !value.is_installed_build(BUILD_ID)))
}}

pub(crate) fn pilot_package_name(url: &str) -> Option<&str> {{
    let prefix = format!("{{}}?channel={{CHANNEL}}&file=", pilot_endpoint());
    let name = url.strip_prefix(&prefix)?;
    let (id, ext) = name.split_once('.')?;
    (lower_hex(id, 32) && matches!(ext, "exe" | "msi" | "dmg")).then_some(name)
}}
'''
    module = Path(__file__).with_name("backupit_private_feed.rs").read_text(encoding="utf-8")
    changes[root / "src/backupit_private_feed.rs"] = module + adapter
    edit("src/lib.rs", "pub(crate) mod update_metadata;", "pub(crate) mod update_metadata;\nmod backupit_private_feed;")
    edit("src/common.rs", "pub fn check_software_update() {\n", '''pub fn check_software_update() {
    #[cfg(all(feature = "flutter", any(target_os = "windows", target_os = "macos")))]
    if std::env::var_os("BACKUPIT_PILOT_TOKEN").is_some() {
        std::thread::spawn(|| {
            let format = if cfg!(target_os = "macos") { "dmg" } else { "exe" };
            clear_software_update_url();
            if let Ok(Some(_)) = crate::backupit_private_feed::pilot_latest(format) {
                let url = crate::backupit_private_feed::pilot_endpoint();
                let event = serde_json::json!({"name": "check_software_update_finish", "url": &url});
                *SOFTWARE_UPDATE_URL.lock().unwrap() = url;
                let _ = crate::flutter::push_global_event(crate::flutter::APP_TYPE_MAIN, event.to_string());
            }
        });
        return;
    }
''')
    edit("src/updater/artifact.rs", "    let release_id = release_id_from_update_url(update_url)?;", '''    if update_url == crate::backupit_private_feed::pilot_endpoint().as_str() {
        let release = crate::backupit_private_feed::pilot_latest(query.format)?
            .ok_or_else(|| hbb_common::anyhow::anyhow!("No newer BackupIT release is available"))?;
        #[cfg(target_os = "macos")]
        let file_name = crate::backupit_private_feed::pilot_package_name(&release.url)
            .ok_or_else(|| hbb_common::anyhow::anyhow!("Invalid BackupIT package name"))?.to_owned();
        return Ok(VerifiedUpdateArtifact {
            version: release.version, url: release.url, size: release.size, sha256: release.sha256,
            #[cfg(target_os = "macos")]
            file_name,
        });
    }
    let release_id = release_id_from_update_url(update_url)?;''')
    edit("src/updater/artifact.rs", "pub fn get_update_download_file_from_url(url: &str) -> Option<PathBuf> {\n", '''pub fn get_update_download_file_from_url(url: &str) -> Option<PathBuf> {
    if let Some(name) = crate::backupit_private_feed::pilot_package_name(url) {
        verified_update_artifact_for_download_url(url).ok()?;
        return Some(std::env::temp_dir().join("BackupIT-Update").join(name));
    }
''')
    edit("src/hbbs_http/downloader.rs", "    let client = create_http_client_async_with_url_strict(&request.url).await?;", '''    let update_token = if crate::backupit_private_feed::pilot_package_name(&request.url).is_some() {
        Some(std::env::var("BACKUPIT_PILOT_TOKEN")?)
    } else {
        None
    };
    let client = if update_token.is_some() {
        reqwest::Client::builder().https_only(true).redirect(reqwest::redirect::Policy::none())
            .connect_timeout(std::time::Duration::from_secs(15))
            .timeout(std::time::Duration::from_secs(300)).build()?
    } else {
        create_http_client_async_with_url_strict(&request.url).await?
    };
    let get = client.get(&request.url);
    let get = if let Some(token) = update_token {
        let mut header = reqwest::header::HeaderValue::from_str(&token)?;
        header.set_sensitive(true);
        get.header("X-BackupIT-Update-Token", header)
    } else {
        get
    };''')
    edit("src/hbbs_http/downloader.rs", "resp = client.get(request.url).send() => {\n            response = resp?.error_for_status()?;", '''resp = get.send() => {
            response = resp?.error_for_status()?;
            if !response.status().is_success() {
                bail!("Update download did not return a successful response");
            }''')
    for path, contents in changes.items():
        path.write_text(contents, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    if os.environ.get("BACKUPIT_PILOT_BRANDED") == "1":
        validate_branded_pilot(os.environ["custom"])
    patch(Path.cwd(), os.environ["BACKUPIT_PILOT_ENDPOINT"], os.environ["BACKUPIT_PILOT_CHANNEL"],
          os.environ["BACKUPIT_PILOT_PUBLIC_KEY"], os.environ.get("BACKUPIT_PILOT_BUILD_ID", os.environ.get("uuid", "")),
          os.environ.get("BACKUPIT_PILOT_ALLOW_RUNTIME_ENDPOINT") == "1",
          os.environ.get("BACKUPIT_PILOT_BUILD_VERSION", ""))
