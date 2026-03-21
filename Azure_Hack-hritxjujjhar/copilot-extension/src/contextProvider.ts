import * as vscode from 'vscode';

export interface WorkspaceContext {
  openFiles: Array<{ name: string; language: string; snippet: string }>;
  workspaceName: string;
  fileCount: number;
}

export async function gatherWorkspaceContext(): Promise<WorkspaceContext> {
  const openFiles: WorkspaceContext['openFiles'] = [];
  const workspaceName = vscode.workspace.name ?? 'unknown';

  for (const tabGroup of vscode.window.tabGroups.all) {
    for (const tab of tabGroup.tabs) {
      if (tab.input instanceof vscode.TabInputText) {
        try {
          const doc = await vscode.workspace.openTextDocument(tab.input.uri);
          const content = doc.getText();
          openFiles.push({
            name: tab.input.uri.fsPath.split('/').pop() ?? 'unknown',
            language: doc.languageId,
            snippet: content.slice(0, 500) + (content.length > 500 ? '\n... (truncated)' : ''),
          });
        } catch {
          // Skip unreadable files
        }
      }
    }
  }

  const allFiles = await vscode.workspace.findFiles('**/*', '**/node_modules/**', 20);

  return {
    openFiles,
    workspaceName,
    fileCount: allFiles.length,
  };
}

export function formatContextForPrompt(ctx: WorkspaceContext): string {
  if (ctx.openFiles.length === 0) {
    return `\n[Workspace: "${ctx.workspaceName}" — no files currently open]`;
  }

  const fileList = ctx.openFiles
    .map(f => `--- ${f.name} (${f.language}) ---\n${f.snippet}`)
    .join('\n\n');

  return `\n\n[Workspace: "${ctx.workspaceName}", ${ctx.fileCount} files]\n${fileList}`;
}