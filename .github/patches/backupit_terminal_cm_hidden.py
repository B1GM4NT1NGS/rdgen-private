from pathlib import Path


def patch_ui_rs(root: Path) -> bool:
    path = root / "src" / "ui.rs"
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8", errors="ignore")
    original = text
    old = """    let hide_cm = *cm::HIDE_CM.lock().unwrap();
    if !args.is_empty() && args[0] == "--cm" && hide_cm {
        // run_app calls expand(show) + run_loop, we use collapse(hide) + run_loop instead to create a hidden window
        frame.collapse(true);
        frame.run_loop();
        return;
    }
    frame.run_app();
"""
    new = """    let _hide_cm = *cm::HIDE_CM.lock().unwrap();
    if !args.is_empty() && args[0] == "--cm" {
        // BackupIT: start CM hidden; cm.tis shows it again for non-terminal sessions.
        frame.collapse(true);
        frame.run_loop();
        return;
    }
    frame.run_app();
"""
    if old in text:
        text = text.replace(old, new, 1)
    else:
        text = text.replace(
            'if !args.is_empty() && args[0] == "--cm" && hide_cm {',
            'if !args.is_empty() && args[0] == "--cm" {',
            1,
        )
        text = text.replace("let hide_cm =", "let _hide_cm =", 1)
        text = text.replace(
            "// run_app calls expand(show) + run_loop, we use collapse(hide) + run_loop instead to create a hidden window",
            "// BackupIT: start CM hidden; cm.tis shows it again for non-terminal sessions.",
            1,
        )
    if text != original:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def patch_cm_tis(root: Path) -> bool:
    path = root / "src" / "ui" / "cm.tis"
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8", errors="ignore")
    original = text
    helper = """
function onlyTerminalConnections() {
    if (connections.length == 0) return false;
    var only_terminal = true;
    connections.map(function(c) {
        if (!c.is_terminal) only_terminal = false;
    });
    return only_terminal;
}
"""
    if "function onlyTerminalConnections()" not in text:
        marker = "function setWindowState(state) {\n"
        if marker in text:
            end = text.find("\n}\n", text.find(marker))
            if end != -1:
                text = text[: end + 3] + helper + text[end + 3 :]
    old = "function bring_to_top(idx=-1) {\n"
    new = """function bring_to_top(idx=-1) {
    if (onlyTerminalConnections()) {
        view.windowState = View.WINDOW_HIDDEN;
        return;
    }
"""
    if old in text and "onlyTerminalConnections()" not in text[text.find(old): text.find(old) + 220]:
        text = text.replace(old, new, 1)
    if text != original:
        path.write_text(text, encoding="utf-8")
        return True
    return False


if __name__ == "__main__":
    root = Path.cwd()
    changed = []
    if patch_ui_rs(root):
        changed.append("src/ui.rs")
    if patch_cm_tis(root):
        changed.append("src/ui/cm.tis")
    if changed:
        print("BackupIT terminal CM hide patch applied: " + ", ".join(changed))
    else:
        print("BackupIT terminal CM hide patch already applied or unsupported source layout")
