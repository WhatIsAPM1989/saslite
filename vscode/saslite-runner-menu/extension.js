"use strict";

const vscode = require("vscode");

function activate(context) {
  const runFullLog = vscode.commands.registerCommand(
    "sasliteRunner.runFullLog",
    () => vscode.commands.executeCommand("code-runner.runCustomCommand"),
  );
  context.subscriptions.push(runFullLog);
}

function deactivate() {}

module.exports = { activate, deactivate };
