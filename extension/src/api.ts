import * as http from "http";
import type { HarnessSettings } from "./config";
import {
  ArtifactContent,
  NewRoundRequest,
  Round,
  RoundDetail,
  EventRecord,
} from "./types";

export class HarnessApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "HarnessApiError";
  }
}

/** Typed client over the harness operator API. */
export class HarnessClient {
  constructor(private settings: HarnessSettings) {}

  update(settings: HarnessSettings): void {
    this.settings = settings;
  }

  async health(): Promise<boolean> {
    try {
      await this.request<{ status: string }>("GET", "/api/health");
      return true;
    } catch {
      return false;
    }
  }

  listRounds(): Promise<Round[]> {
    return this.request<Round[]>("GET", "/api/rounds");
  }

  getRound(id: string): Promise<RoundDetail> {
    return this.request<RoundDetail>("GET", `/api/rounds/${encodeURIComponent(id)}`);
  }

  events(id: string, afterId = 0): Promise<EventRecord[]> {
    return this.request<EventRecord[]>(
      "GET",
      `/api/rounds/${encodeURIComponent(id)}/events?after=${afterId}`,
    );
  }

  async diff(id: string): Promise<string> {
    const body = await this.request<{ content: string }>(
      "GET",
      `/api/rounds/${encodeURIComponent(id)}/diff`,
    );
    return body.content;
  }

  artifact(artifactId: number): Promise<ArtifactContent> {
    return this.request<ArtifactContent>("GET", `/api/artifacts/${artifactId}`);
  }

  createRound(req: NewRoundRequest): Promise<Round> {
    return this.request<Round>("POST", "/api/rounds", req);
  }

  runRound(id: string, dryRun: boolean): Promise<{ started: boolean }> {
    return this.request("POST", `/api/rounds/${encodeURIComponent(id)}/run`, {
      dry_run: dryRun,
    });
  }

  approveRound(id: string, run: boolean, dryRun: boolean): Promise<Round> {
    return this.action(id, "approve", run, dryRun);
  }

  cancelRound(id: string): Promise<Round> {
    return this.action(id, "cancel", false, false);
  }

  retryRound(id: string, run: boolean, dryRun: boolean): Promise<Round> {
    return this.action(id, "retry", run, dryRun);
  }

  promoteRound(id: string): Promise<Round> {
    return this.action(id, "promote", false, false);
  }

  private action(id: string, action: string, run: boolean, dryRun: boolean): Promise<Round> {
    return this.request<Round>("POST", `/api/rounds/${encodeURIComponent(id)}/${action}`, {
      run,
      dry_run: dryRun,
    });
  }

  private request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const payload = body === undefined ? undefined : Buffer.from(JSON.stringify(body), "utf-8");
    const headers: http.OutgoingHttpHeaders = { Accept: "application/json" };
    if (payload) {
      headers["Content-Type"] = "application/json";
      headers["Content-Length"] = payload.length;
    }
    if (this.settings.token) {
      headers["Authorization"] = `Bearer ${this.settings.token}`;
    }

    const options: http.RequestOptions = {
      host: this.settings.host,
      port: this.settings.port,
      path,
      method,
      headers,
      timeout: 15000,
    };

    return new Promise<T>((resolve, reject) => {
      const req = http.request(options, (res) => {
        const chunks: Buffer[] = [];
        res.on("data", (chunk) => chunks.push(chunk as Buffer));
        res.on("end", () => {
          const text = Buffer.concat(chunks).toString("utf-8");
          const status = res.statusCode ?? 0;
          if (status >= 200 && status < 300) {
            resolve(text ? (JSON.parse(text) as T) : (undefined as T));
            return;
          }
          let message = text;
          try {
            const parsed = JSON.parse(text) as { error?: string };
            if (parsed.error) {
              message = parsed.error;
            }
          } catch {
            /* keep raw text */
          }
          reject(new HarnessApiError(message || `HTTP ${status}`, status));
        });
      });
      req.on("timeout", () => req.destroy(new Error("request timed out")));
      req.on("error", (err) => reject(err));
      if (payload) {
        req.write(payload);
      }
      req.end();
    });
  }
}
