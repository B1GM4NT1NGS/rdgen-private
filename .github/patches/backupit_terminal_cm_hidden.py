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
        // BackupIT: start CM hidden; cm.tis shows it again for desktop sessions.
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
            "// BackupIT: start CM hidden; cm.tis shows it again for desktop sessions.",
            1,
        )
    text = text.replace(
        "// BackupIT: start CM hidden; cm.tis shows it again for non-terminal sessions.",
        "// BackupIT: start CM hidden; cm.tis shows it again for desktop sessions.",
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
function isBackupITNonDesktopConnection(c) {
    return c && (c.is_terminal || (c.port_forward && c.port_forward.length > 0));
}

function onlyBackupITNonDesktopConnections() {
    if (connections.length == 0) return false;
    var only_non_desktop = true;
    connections.map(function(c) {
        if (!isBackupITNonDesktopConnection(c)) only_non_desktop = false;
    });
    return only_non_desktop;
}
"""
    old_helper = """function onlyTerminalConnections() {
    if (connections.length == 0) return false;
    var only_terminal = true;
    connections.map(function(c) {
        if (!c.is_terminal) only_terminal = false;
    });
    return only_terminal;
}
"""
    if old_helper in text:
        text = text.replace(old_helper, helper.strip() + "\n", 1)
    if "function onlyBackupITNonDesktopConnections()" not in text:
        marker = "function setWindowState(state) {\n"
        if marker in text:
            end = text.find("\n}\n", text.find(marker))
            if end != -1:
                text = text[: end + 3] + helper + text[end + 3 :]
    old = "function bring_to_top(idx=-1) {\n"
    new = """function bring_to_top(idx=-1) {
    if (onlyBackupITNonDesktopConnections()) {
        view.windowState = View.WINDOW_HIDDEN;
        return;
    }
"""
    legacy_new = """function bring_to_top(idx=-1) {
    if (onlyTerminalConnections()) {
        view.windowState = View.WINDOW_HIDDEN;
        return;
    }
"""
    if legacy_new in text:
        text = text.replace(legacy_new, new, 1)
    if old in text and "onlyBackupITNonDesktopConnections()" not in text[text.find(old): text.find(old) + 260]:
        text = text.replace(old, new, 1)
    if text != original:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def patch_flutter_main(root: Path) -> bool:
    path = root / "flutter" / "lib" / "main.dart"
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8", errors="ignore")
    original = text
    old = """  final hide = await bind.cmGetConfig(name: "hide_cm") == 'true';
  gFFI.serverModel.hideCm = hide;
  if (hide) {
    await hideCmWindow(isStartup: true);
  } else {
    await showCmWindow(isStartup: true);
  }
"""
    new = """  final hide = await bind.cmGetConfig(name: "hide_cm") == 'true';
  gFFI.serverModel.hideCm = hide;
  // BackupIT: start CM hidden; ServerModel shows it again for desktop sessions.
  await hideCmWindow(isStartup: true);
"""
    if old in text:
        text = text.replace(old, new, 1)
    if text != original:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def patch_flutter_server_model(root: Path) -> bool:
    path = root / "flutter" / "lib" / "models" / "server_model.dart"
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8", errors="ignore")
    original = text

    clients_getter = "  List<Client> get clients => _clients;\n"
    visibility_helpers = """  List<Client> get clients => _clients;

  bool get hasBackupITDesktopConnections =>
      _clients.any((client) => !client.isBackupITNonDesktop);

  bool get onlyBackupITNonDesktopConnections =>
      _clients.isNotEmpty && !hasBackupITDesktopConnections;

  Future<void> updateBackupITCmVisibility() async {
    if (desktopType != DesktopType.cm) return;
    if (_clients.isEmpty || onlyBackupITNonDesktopConnections) {
      await hideCmWindow();
    } else if (!hideCm) {
      await showCmWindow();
    }
  }
"""
    if "hasBackupITDesktopConnections" not in text and clients_getter in text:
        text = text.replace(clients_getter, visibility_helpers, 1)

    text = text.replace(
        """          if (_clients.isEmpty) {
            hideCmWindow();
            if (_zeroClientLengthCounter++ == 12) {
              // 6 second
              windowManager.close();
            }
          } else {
            _zeroClientLengthCounter = 0;
            if (!hideCm) showCmWindow();
          }
""",
        """          if (_clients.isEmpty) {
            hideCmWindow();
            if (_zeroClientLengthCounter++ == 12) {
              // 6 second
              windowManager.close();
            }
          } else {
            _zeroClientLengthCounter = 0;
            await updateBackupITCmVisibility();
          }
""",
        1,
    )

    text = text.replace(
        """    if (desktopType == DesktopType.cm) {
      if (_clients.isEmpty) {
        hideCmWindow();
      } else if (!hideCm) {
        showCmWindow();
      }
    }
""",
        """    if (desktopType == DesktopType.cm) {
      await updateBackupITCmVisibility();
    }
""",
        1,
    )

    text = text.replace(
        """      if (desktopType == DesktopType.cm && !hideCm) {
        showCmWindow();
      }
""",
        """      updateBackupITCmVisibility();
""",
        1,
    )

    text = text.replace(
        """    Future.delayed(Duration.zero, () async {
      if (!hideCm) windowOnTop(null);
    });
    // Only do the hidden task when on Desktop.
    if (client.authorized && isDesktop) {
      cmHiddenTimer = Timer(const Duration(seconds: 3), () {
        if (!hideCm) windowManager.minimize();
        cmHiddenTimer = null;
      });
    }
""",
        """    Future.delayed(Duration.zero, () async {
      if (!hideCm && !client.isBackupITNonDesktop) windowOnTop(null);
    });
    // Only do the hidden task when on Desktop.
    if (client.authorized && isDesktop && !client.isBackupITNonDesktop) {
      cmHiddenTimer = Timer(const Duration(seconds: 3), () {
        if (!hideCm) windowManager.minimize();
        cmHiddenTimer = null;
      });
    }
""",
        1,
    )

    client_field = """  bool incomingVoiceCall = false;

  RxInt unreadChatMessageCount = 0.obs;
"""
    client_method = """  bool incomingVoiceCall = false;

  bool get isBackupITNonDesktop =>
      isTerminal || portForward.trim().isNotEmpty;

  RxInt unreadChatMessageCount = 0.obs;
"""
    if "bool get isBackupITNonDesktop" not in text and client_field in text:
        text = text.replace(client_field, client_method, 1)

    text = text.replace(
        "    portForward = json['port_forward'];",
        "    portForward = json['port_forward'] ?? '';",
        1,
    )

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
    if patch_flutter_main(root):
        changed.append("flutter/lib/main.dart")
    if patch_flutter_server_model(root):
        changed.append("flutter/lib/models/server_model.dart")
    if changed:
        print("BackupIT terminal CM hide patch applied: " + ", ".join(changed))
    else:
        print("BackupIT terminal CM hide patch already applied or unsupported source layout")
