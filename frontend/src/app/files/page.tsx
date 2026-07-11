"use client";

import Link from "next/link";
import { ChangeEvent, useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  Download,
  File,
  Files,
  LoaderCircle,
  Trash2,
  Upload,
} from "lucide-react";
import { AuthBoundary } from "@/components/auth/AuthBoundary";
import { AccountMenu } from "@/components/auth/AccountMenu";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/providers/Auth";

type StoredFile = {
  id: string;
  filename: string;
  content_type?: string;
  size_bytes: number;
  storage_backend: string;
  created_at: string;
};

const BYTES_PER_KIBIBYTE = 1024;
const BYTES_PER_MEBIBYTE = BYTES_PER_KIBIBYTE * BYTES_PER_KIBIBYTE;

function formatSize(bytes: number) {
  if (bytes < BYTES_PER_KIBIBYTE) return `${bytes} B`;
  if (bytes < BYTES_PER_MEBIBYTE) {
    return `${(bytes / BYTES_PER_KIBIBYTE).toFixed(1)} KB`;
  }
  return `${(bytes / BYTES_PER_MEBIBYTE).toFixed(1)} MB`;
}

function FilesContent() {
  const { authFetch } = useAuth();
  const [files, setFiles] = useState<StoredFile[]>([]);
  const [uploading, setUploading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const backend =
    process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

  const load = useCallback(async () => {
    const response = await authFetch(`${backend}/files`);
    if (response.ok) setFiles((await response.json()).files || []);
  }, [authFetch, backend]);

  useEffect(() => {
    load();
  }, [load]);

  const upload = async (event: ChangeEvent<HTMLInputElement>) => {
    setUploading(true);
    for (const file of Array.from(event.target.files || [])) {
      const form = new FormData();
      form.append("file", file);
      await authFetch(`${backend}/files`, { method: "POST", body: form });
    }
    event.target.value = "";
    setUploading(false);
    load();
  };

  const download = async (item: StoredFile) => {
    const response = await authFetch(`${backend}/files/${item.id}/content`);
    if (!response.ok) return;
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = item.filename;
    link.click();
    URL.revokeObjectURL(url);
  };

  const remove = async (item: StoredFile) => {
    if (!window.confirm(`删除 ${item.filename}？`)) return;
    await authFetch(`${backend}/files/${item.id}`, { method: "DELETE" });
    load();
  };

  return (
    <main className="min-h-dvh bg-slate-50">
      <header className="sticky top-0 z-20 border-b bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-3 sm:px-6">
          <Link
            href="/"
            className="rounded-lg p-2 hover:bg-slate-100"
          >
            <ArrowLeft className="size-5" />
          </Link>
          <Files className="size-5" />
          <h1 className="flex-1 font-semibold">文件存储</h1>
          <AccountMenu />
        </div>
      </header>
      <div className="mx-auto max-w-6xl p-4 sm:p-6">
        <section className="mb-5 flex flex-col justify-between gap-3 rounded-2xl border bg-white p-5 sm:flex-row sm:items-center">
          <div>
            <h2 className="font-semibold">图片与文件</h2>
            <p className="mt-1 text-sm text-slate-500">
              文件按账号隔离，可使用本地卷或 S3 兼容对象存储。
            </p>
          </div>
          <Button
            onClick={() => inputRef.current?.click()}
            disabled={uploading}
          >
            {uploading ? <LoaderCircle className="animate-spin" /> : <Upload />}{" "}
            上传文件
          </Button>
          <input
            ref={inputRef}
            type="file"
            multiple
            className="hidden"
            onChange={upload}
          />
        </section>
        <section className="overflow-hidden rounded-2xl border bg-white">
          {files.length === 0 ? (
            <p className="p-10 text-center text-sm text-slate-500">
              还没有文件。
            </p>
          ) : (
            <div className="divide-y">
              {files.map((item) => (
                <div
                  key={item.id}
                  className="flex items-center gap-3 p-4"
                >
                  <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-slate-100">
                    <File className="size-5" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">
                      {item.filename}
                    </p>
                    <p className="mt-1 text-xs text-slate-500">
                      {formatSize(item.size_bytes)} · {item.storage_backend} ·{" "}
                      {new Date(item.created_at).toLocaleString()}
                    </p>
                  </div>
                  <button
                    onClick={() => download(item)}
                    className="rounded-lg p-2 hover:bg-slate-100"
                    title="下载"
                  >
                    <Download className="size-4" />
                  </button>
                  <button
                    onClick={() => remove(item)}
                    className="rounded-lg p-2 text-red-600 hover:bg-red-50"
                    title="删除"
                  >
                    <Trash2 className="size-4" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </main>
  );
}

export default function FilesPage() {
  return (
    <AuthBoundary>
      <FilesContent />
    </AuthBoundary>
  );
}
