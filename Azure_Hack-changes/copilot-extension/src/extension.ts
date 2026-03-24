import * as vscode from 'vscode';
import { registerNexusParticipant } from './nexusParticipant';

export function activate(context: vscode.ExtensionContext) {
  console.log('Nexus Copilot Extension activated!');
  registerNexusParticipant(context);

  const resetCmd = vscode.commands.registerCommand('nexus.resetSession', () => {
    vscode.window.showInformationMessage('Nexus session reset. Start fresh with @nexus build me a...');
  });

  context.subscriptions.push(resetCmd);
}

export function deactivate() {}