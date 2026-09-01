import * as vscode from "vscode";

export const SCHEME = "icm";

/**
 * Serves harness-fetched text (worktree diffs, artifact contents, event trails)
 * as read-only virtual documents. Content is registered by the command that
 * opens the document, keyed by the URI path.
 */
export class HarnessDocumentProvider implements vscode.TextDocumentContentProvider {
  private readonly _onDidChange = new vscode.EventEmitter<vscode.Uri>();
  readonly onDidChange = this._onDidChange.event;
  private readonly store = new Map<string, string>();

  provideTextDocumentContent(uri: vscode.Uri): string {
    return this.store.get(uri.toString()) ?? "";
  }

  /**
   * Register `content` under a virtual URI and return it.
   * @param path  human-readable path segment, e.g. `diff/r-123.diff`
   */
  set(path: string, content: string): vscode.Uri {
    const uri = vscode.Uri.from({ scheme: SCHEME, path: `/${path}` });
    this.store.set(uri.toString(), content);
    this._onDidChange.fire(uri);
    return uri;
  }
}

export async function openVirtualDocument(
  uri: vscode.Uri,
  language: string,
  options?: vscode.TextDocumentShowOptions,
): Promise<void> {
  const doc = await vscode.workspace.openTextDocument(uri);
  await vscode.languages.setTextDocumentLanguage(doc, language);
  await vscode.window.showTextDocument(doc, { preview: true, ...options });
}
