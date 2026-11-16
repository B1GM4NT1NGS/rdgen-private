use hbb_common::{
    anyhow::{anyhow, ensure},
    base64::{engine::general_purpose::STANDARD, Engine as _},
    sodiumoxide::{self, crypto::sign::{verify_detached, PublicKey, Signature}},
    ResultType,
};
use reqwest::{blocking::{Client, Response}, redirect::Policy};
use serde_derive::Deserialize;
use sha2::{Digest, Sha256};
use std::{io::{Read, Write}, time::Duration};

const CONTEXT: &[u8] = b"BackupIT private update v1\n";
const ORIGIN: &str = "https://backupit.co.uk/";
const MAX_MANIFEST: u64 = 16_384;
const MAX_PACKAGE: u64 = 512 * 1024 * 1024;

#[derive(Deserialize)]
struct Envelope {
    metadata: String,
    signature: String,
}

#[derive(Debug, Deserialize)]
pub(crate) struct Release {
    schema: u32,
    channel: String,
    pub version: String,
    pub url: String,
    format: String,
    pub size: u64,
    pub sha256: String,
    #[serde(default)]
    pub build_id: String,
}

impl Release {
    pub(crate) fn is_installed_build(&self, installed_build_id: &str) -> bool {
        !installed_build_id.is_empty() && self.build_id == installed_build_id
    }
}

pub(crate) struct PrivateFeed<'a> {
    base: &'a str,
    channel: &'a str,
    token: &'a str,
    client: Client,
}

fn lower_hex(value: &str, length: usize) -> bool {
    value.len() == length && value.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

fn version_tuple(value: &str) -> Option<[u32; 4]> {
    let mut parts = value.strip_prefix("BackupIT-")?.split('.');
    let mut tuple = [0; 4];
    for part in &mut tuple {
        let value = parts.next()?;
        if value.is_empty() || !value.bytes().all(|b| b.is_ascii_digit()) {
            return None;
        }
        *part = value.parse().ok()?;
    }
    if parts.next().is_some() || !(1..=12).contains(&tuple[1]) || !(1..=31).contains(&tuple[2]) || tuple[3] == 0 {
        return None;
    }
    Some(tuple)
}

impl<'a> PrivateFeed<'a> {
    pub(crate) fn new(base: &'a str, channel: &'a str, token: &'a str) -> ResultType<Self> {
        let directory = base.strip_prefix(ORIGIN).and_then(|value| value.strip_suffix("/index.php"));
        ensure!(directory.is_some_and(|value| lower_hex(value, 24)), "invalid BackupIT update endpoint");
        ensure!(matches!(channel, "windows" | "windows-admin" | "windows-x86" | "windows-ask-only"
            | "windows-ask-pass" | "android" | "macos" | "linux"), "invalid BackupIT update channel");
        ensure!(lower_hex(token, 64), "BackupIT update enrollment required");
        let client = Client::builder().https_only(true).redirect(Policy::none())
            .timeout(Duration::from_secs(300)).connect_timeout(Duration::from_secs(15)).build()?;
        Ok(Self { base, channel, token, client })
    }

    fn prefix(&self) -> String {
        format!("{}?channel={}&file=", self.base, self.channel)
    }

    fn request(&self, url: &str) -> ResultType<Response> {
        let mut token = reqwest::header::HeaderValue::from_str(self.token)?;
        token.set_sensitive(true);
        let response = self.client.get(url).header("X-BackupIT-Update-Token", token).send()?;
        ensure!(response.status().is_success(), "BackupIT update request returned {}", response.status());
        Ok(response)
    }

    pub(crate) fn latest(&self, public_key: [u8; 32], format: &str, installed: &str) -> ResultType<Option<Release>> {
        let response = self.request(&(self.prefix() + "latest.json"))?;
        let mut bytes = Vec::new();
        response.take(MAX_MANIFEST + 1).read_to_end(&mut bytes)?;
        self.verify(&bytes, public_key, format, installed)
    }

    fn verify(&self, bytes: &[u8], public_key: [u8; 32], format: &str, installed: &str) -> ResultType<Option<Release>> {
        ensure!(bytes.len() as u64 <= MAX_MANIFEST, "BackupIT manifest too large");
        let envelope: Envelope = serde_json::from_slice(bytes)?;
        let metadata = STANDARD.decode(envelope.metadata)?;
        let signature = Signature::from_bytes(&STANDARD.decode(envelope.signature)?)
            .map_err(|_| anyhow!("invalid BackupIT signature encoding"))?;
        sodiumoxide::init().map_err(|_| anyhow!("could not initialize update signature verification"))?;
        let signed = [CONTEXT, metadata.as_slice()].concat();
        ensure!(verify_detached(&signature, &signed, &PublicKey(public_key)), "invalid BackupIT update signature");
        let release: Release = serde_json::from_slice(&metadata)?;
        ensure!(release.schema == 1 && release.channel == self.channel && release.format == format,
            "BackupIT release does not match this client");
        ensure!((1..=MAX_PACKAGE).contains(&release.size) && lower_hex(&release.sha256, 64), "invalid BackupIT package digest or size");
        self.package_url(&release)?;
        let next = version_tuple(&release.version).ok_or_else(|| anyhow!("invalid BackupIT release version"))?;
        let current = version_tuple(installed).ok_or_else(|| anyhow!("invalid installed BackupIT version"))?;
        Ok((next > current).then_some(release))
    }

    fn package_url<'b>(&self, release: &'b Release) -> ResultType<&'b str> {
        let allowed = match self.channel {
            "macos" => matches!(release.format.as_str(), "dmg" | "pkg" | "zip"),
            "linux" => matches!(release.format.as_str(), "deb" | "rpm" | "appimage" | "tar.gz" | "zip"),
            "android" => matches!(release.format.as_str(), "apk" | "aab" | "zip"),
            _ => matches!(release.format.as_str(), "exe" | "msi" | "zip"),
        };
        ensure!(allowed && release.channel == self.channel, "invalid BackupIT package format or channel");
        let suffix = format!(".{}", release.format);
        let opaque = release.url.strip_prefix(self.prefix().as_str()).and_then(|name| name.strip_suffix(&suffix));
        ensure!(opaque.is_some_and(|name| lower_hex(name, 32)), "invalid signed BackupIT package URL");
        Ok(&release.url)
    }

    // The caller owns the staging file and must not use it if verification fails.
    pub(crate) fn download(&self, release: &Release, staging: &mut impl Write) -> ResultType<()> {
        let response = self.request(self.package_url(release)?)?;
        verify_stream(response, staging, release)
    }
}

fn verify_stream(source: impl Read, staging: &mut impl Write, release: &Release) -> ResultType<()> {
    let mut buf = [0; 64 * 1024];
    let mut source = source.take(release.size + 1);
    let mut digest = Sha256::new();
    let mut total = 0;
    loop {
        let length = source.read(&mut buf)?;
        if length == 0 {
            break;
        }
        total += length as u64;
        ensure!(total <= release.size, "BackupIT package exceeds signed size");
        digest.update(&buf[..length]);
        staging.write_all(&buf[..length])?;
    }
    ensure!(total == release.size && format!("{:x}", digest.finalize()) == release.sha256,
        "BackupIT package does not match signed size or digest");
    staging.flush()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use hbb_common::sodiumoxide::crypto::sign::{gen_keypair, sign_detached};
    use serde_json::json;

    #[test]
    fn downloader_rejects_short_overlong_and_modified_packages() {
        let package = b"test";
        let release = Release {
            schema: 1, channel: "windows-admin".into(), version: "BackupIT-2026.11.16.2".into(),
            url: String::new(), format: "exe".into(), size: package.len() as u64,
            sha256: format!("{:x}", Sha256::digest(package)),
            build_id: String::new(),
        };
        let mut stage = Vec::new();
        verify_stream(&package[..], &mut stage, &release).unwrap();
        assert_eq!(stage, package);
        for other in [b"tes".as_slice(), b"test!", b"Test"] {
            assert!(verify_stream(other, &mut Vec::new(), &release).is_err());
        }
    }

    #[test]
    fn verifies_signed_channel_url_and_monotonic_version() {
        let base = format!("{ORIGIN}{}/index.php", "a".repeat(24));
        let token = "a".repeat(64);
        let feed = PrivateFeed::new(&base, "windows-admin", &token).unwrap();
        assert!(PrivateFeed::new("https://backupit.co.uk.example/", "windows-admin", &token).is_err());
        sodiumoxide::init().unwrap();
        let (public, secret) = gen_keypair();
        let make_envelope = |channel: &str, url: &str| {
            let raw = serde_json::to_vec(&json!({
                "schema":1, "channel":channel, "version":"BackupIT-2026.11.16.2",
                "url":url, "format":"exe", "size":123, "sha256":"a".repeat(64), "build_id":"generated-build-2"
            })).unwrap();
            let signature = sign_detached(&[CONTEXT, raw.as_slice()].concat(), &secret);
            serde_json::to_vec(&json!({"metadata":STANDARD.encode(raw), "signature":STANDARD.encode(signature.to_bytes())})).unwrap()
        };
        let url = format!("{}{}.exe", feed.prefix(), "b".repeat(32));
        let envelope = make_envelope("windows-admin", &url);
        let release = feed.verify(&envelope, public.0, "exe", "BackupIT-2026.11.16.1").unwrap().unwrap();
        assert!(release.is_installed_build("generated-build-2"));
        assert!(!release.is_installed_build("generated-build-1"));
        assert!(!release.is_installed_build(""));
        assert!(feed.verify(&envelope, public.0, "exe", "BackupIT-2026.11.16.2").unwrap().is_none());
        assert!(feed.verify(&envelope, public.0, "exe", "BackupIT-2026.11.16.10").unwrap().is_none());
        assert!(feed.verify(&envelope, [0; 32], "exe", "BackupIT-2026.11.16.1").is_err());
        assert!(feed.verify(&make_envelope("windows", &url), public.0, "exe", "BackupIT-2026.11.16.1").is_err());
        assert!(feed.verify(&make_envelope("windows-admin", "https://example.com/override.exe"), public.0, "exe", "BackupIT-2026.11.16.1").is_err());
    }
}
