from pathlib import Path


RUST = r'''
// BackupIT: hash the firmware UUID; never send the raw hardware identifier.
#[cfg(windows)]
fn backupit_hardware_id() -> String {
    use sha2::{Digest, Sha256};
    #[link(name = "kernel32")]
    extern "system" {
        fn GetSystemFirmwareTable(provider: u32, table: u32, buffer: *mut std::ffi::c_void, size: u32) -> u32;
    }
    let provider = u32::from_be_bytes(*b"RSMB");
    let size = unsafe { GetSystemFirmwareTable(provider, 0, std::ptr::null_mut(), 0) };
    if size < 8 || size > 1_048_576 { return String::new(); }
    let mut data = vec![0u8; size as usize];
    let read = unsafe { GetSystemFirmwareTable(provider, 0, data.as_mut_ptr().cast(), size) };
    if read != size { return String::new(); }
    let length = u32::from_le_bytes([data[4], data[5], data[6], data[7]]) as usize;
    if length > data.len() - 8 { return String::new(); }
    let end = 8 + length;
    let mut pos = 8;
    while pos + 4 <= end {
        let kind = data[pos];
        let len = data[pos + 1] as usize;
        if len < 4 || pos + len > end { break; }
        if kind == 1 && len >= 24 {
            let id = &data[pos + 8..pos + 24];
            if id.iter().all(|b| *b == 0) || id.iter().all(|b| *b == 255) { return String::new(); }
            let mut hash = Sha256::new();
            hash.update(b"BackupIT-SMBIOS-UUID-v1:");
            hash.update(id);
            return format!("{:x}", hash.finalize());
        }
        if kind == 127 { break; }
        pos += len;
        while pos + 1 < end && !(data[pos] == 0 && data[pos + 1] == 0) { pos += 1; }
        pos += 2;
    }
    String::new()
}

'''


def apply(root=Path(".")):
    path = root / "src/common.rs"
    text = path.read_text(encoding="utf-8")
    if "fn backupit_hardware_id()" in text:
        if 'out["hwid"]' not in text:
            raise RuntimeError("Incomplete BackupIT HWID patch")
        return
    marker = "pub fn get_sysinfo() -> serde_json::Value {"
    start = text.find(marker)
    end = text.find("\n    out\n}", start)
    if start < 0 or end < 0:
        raise RuntimeError("RustDesk sysinfo structure changed; HWID patch needs review")
    addition = '''
    #[cfg(windows)]
    {
        let hwid = backupit_hardware_id();
        if !hwid.is_empty() { out["hwid"] = json!(hwid); }
    }'''
    text = text[:end] + addition + text[end:]
    text = text.replace(marker, RUST + marker, 1)
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    apply()
    print("BackupIT hashed SMBIOS HWID reporting applied")
