import * as vscode from 'vscode';
import { sendToClarify, getBuildContext, getAgentLogs, generateProjectId } from './directorClient';
import { gatherWorkspaceContext, formatContextForPrompt } from './contextProvider';

const projectSessions = new Map<string, string>();

export function registerNexusParticipant(context: vscode.ExtensionContext) {
  const participant = vscode.chat.createChatParticipant('nexus.agent', handleNexusRequest);
  participant.iconPath = new vscode.ThemeIcon('rocket');
  context.subscriptions.push(participant);
}

async function handleNexusRequest(
  request: vscode.ChatRequest,
  chatContext: vscode.ChatContext,
  stream: vscode.ChatResponseStream,
  token: vscode.CancellationToken
): Promise<void> {
  const sessionKey = 'default';

  if (request.command === 'debug' || looksLikeDebugRequest(request.prompt)) {
    await handleDebugMode(request, stream, token, sessionKey);
  } else if (request.command === 'explain') {
    await handleExplainMode(stream, token, sessionKey);
  } else {
    await handleBuildMode(request, chatContext, stream, token, sessionKey);
  }
}

async function handleBuildMode(
  request: vscode.ChatRequest,
  _chatContext: vscode.ChatContext,
  stream: vscode.ChatResponseStream,
  _token: vscode.CancellationToken,
  sessionKey: string
): Promise<void> {
  let projectId = projectSessions.get(sessionKey);
  if (!projectId) {
    projectId = generateProjectId();
    projectSessions.set(sessionKey, projectId);
    stream.markdown(`🚀 **New build started** \`${projectId}\`\n\n`);
  }

  stream.progress('Gathering workspace context...');
  const wsContext = await gatherWorkspaceContext();
  const contextSuffix = formatContextForPrompt(wsContext);
  const enrichedInput = request.prompt + contextSuffix;

  stream.progress('Sending to Director agent...');
  const reply = await sendToClarify(projectId, enrichedInput);

  stream.markdown(`**🤖 Director:**\n\n${reply.director_reply}\n\n`);

  if (reply.state === 'BUILDING') {
    stream.markdown(`---\n⚙️ *Build started! Open the Command Center to watch agents work.*\n`);
    stream.button({
      command: 'vscode.open',
      arguments: [vscode.Uri.parse('http://localhost:3000')],
      title: '$(globe) Open Command Center',
    });
  } else {
    stream.markdown(`\n*Reply to continue, or use \`@nexus /build\` to start fresh.*\n`);
  }
}

async function handleDebugMode(
  request: vscode.ChatRequest,
  stream: vscode.ChatResponseStream,
  _token: vscode.CancellationToken,
  sessionKey: string
): Promise<void> {
  const projectId = projectSessions.get(sessionKey);
  if (!projectId) {
    stream.markdown(`⚠️ No active build session. Start one with \`@nexus build me a...\``);
    return;
  }

  const agentName = extractAgentName(request.prompt) ?? 'backend-engineer';
  stream.progress(`Fetching logs for: ${agentName}...`);
  const status = await getAgentLogs(agentName, projectId);

  stream.markdown(`## 🔍 Debug: \`${status.agent_id}\`\n\n`);
  stream.markdown(`**Status:** ${stateEmoji(status.state)} ${status.state}\n\n`);

  if (status.error) {
    stream.markdown(`**❌ Error:** \`${status.error}\`\n\n`);
  }

  stream.markdown(`**📋 Logs:**\n\`\`\`\n${status.logs.join('\n')}\n\`\`\`\n\n`);
  stream.markdown(`**💰 Tokens:** ${status.tokens_used} (~$${status.cost.toFixed(4)})\n\n`);

  if (status.state === 'FAILED') {
    stream.markdown(`**💡 Suggestions:**\n${generateDebugSuggestions(status.error ?? '')}`);
  }
}

async function handleExplainMode(
  stream: vscode.ChatResponseStream,
  _token: vscode.CancellationToken,
  sessionKey: string
): Promise<void> {
  const projectId = projectSessions.get(sessionKey);
  if (!projectId) {
    stream.markdown(`⚠️ No active build session. Start with \`@nexus build me a...\``);
    return;
  }

  stream.progress('Loading build context...');
  const ctx = await getBuildContext(projectId);

  stream.markdown(`## 🏗️ Build Architecture\n\n`);
  for (const [key, val] of Object.entries(ctx.task_ledger)) {
    stream.markdown(`- **${key}**: ${val}\n`);
  }

  stream.markdown(`\n**🤖 Agents (${ctx.aeg.nodes.length}):**\n`);
  for (const node of ctx.aeg.nodes as Array<{ id: string; agent_type: string; state: string }>) {
    stream.markdown(`- ${stateEmoji(node.state)} \`${node.agent_type}\` — ${node.state}\n`);
  }
}

function looksLikeDebugRequest(prompt: string): boolean {
  return ['why', 'failed', 'error', 'debug', 'broke', 'fix'].some(k => prompt.toLowerCase().includes(k));
}

function extractAgentName(prompt: string): string | null {
  return ['backend', 'frontend', 'database', 'devops', 'security', 'qa', 'healer']
    .find(a => prompt.toLowerCase().includes(a)) ?? null;
}

function stateEmoji(state: string): string {
  return ({ PENDING: '⏳', RUNNING: '🔄', COMPLETED: '✅', FAILED: '❌', DONE: '✅' } as Record<string, string>)[state] ?? '❓';
}

function generateDebugSuggestions(error: string): string {
  if (error.toLowerCase().includes('timeout')) {
    return `1. Check Azure SQL firewall rules\n2. Verify connection string in Key Vault\n3. Try SQLite for local dev\n`;
  }
  if (error.toLowerCase().includes('auth') || error.toLowerCase().includes('401')) {
    return `1. Verify API keys in Azure Key Vault\n2. Check Azure AD permissions\n3. Regenerate service principal\n`;
  }
  return `1. Check logs above for the exact error\n2. The Healer agent may auto-fix this\n3. Check Command Center for status\n`;
}