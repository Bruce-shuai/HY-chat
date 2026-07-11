"use client";

import Link from "next/link";
import {
  ChangeEvent,
  FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  ArrowLeft,
  ImageIcon,
  Images,
  LoaderCircle,
  Sparkles,
  Upload,
  X,
} from "lucide-react";
import { AuthBoundary } from "@/components/auth/AuthBoundary";
import { AccountMenu } from "@/components/auth/AccountMenu";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/providers/Auth";

type ImageGeneration = {
  id: number;
  status: string;
  mode: "text_to_image" | "image_to_image";
  provider: string;
  model: string;
  prompt: string;
  image_url?: string | null;
  output_file_id?: string | null;
  source_file_id?: string | null;
  created_at?: string;
};

const IMAGE_SIZES = ["1024x1024", "1536x1024", "1024x1536"];
const IMAGE_QUALITIES = ["auto", "low", "medium", "high"];

function ImageStudioContent() {
  const { authFetch } = useAuth();
  const [source, setSource] = useState<File | null>(null);
  const [sourcePreview, setSourcePreview] = useState<string | null>(null);
  const [resultPreview, setResultPreview] = useState<string | null>(null);
  const [history, setHistory] = useState<ImageGeneration[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const sourceInput = useRef<HTMLInputElement>(null);
  const backend =
    process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

  const loadHistory = useCallback(async () => {
    const response = await authFetch(`${backend}/images/generations`);
    if (response.ok) {
      setHistory((await response.json()).generations || []);
    }
  }, [authFetch, backend]);

  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  const chooseSource = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] || null;
    if (sourcePreview) URL.revokeObjectURL(sourcePreview);
    setSource(file);
    setSourcePreview(file ? URL.createObjectURL(file) : null);
  };

  const loadOutput = async (fileId: string) => {
    const response = await authFetch(`${backend}/files/${fileId}/content`);
    if (!response.ok) return;
    if (resultPreview) URL.revokeObjectURL(resultPreview);
    setResultPreview(URL.createObjectURL(await response.blob()));
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setLoading(true);
    setError("");
    const data = new FormData(event.currentTarget);
    if (source) data.set("source_image", source);
    const response = await authFetch(`${backend}/images/generations`, {
      method: "POST",
      body: data,
    });
    const result = await response.json();
    if (!response.ok) {
      setError(result.detail || "图片生成失败");
    } else if (result.output_file_id) {
      await loadOutput(result.output_file_id);
      await loadHistory();
    }
    setLoading(false);
  };

  return (
    <main className="min-h-dvh bg-slate-50">
      <header className="sticky top-0 z-20 border-b bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center gap-3 px-4 py-3 sm:px-6">
          <Link
            href="/"
            className="rounded-lg p-2 hover:bg-slate-100"
          >
            <ArrowLeft className="size-5" />
          </Link>
          <Images className="size-5" />
          <h1 className="flex-1 font-semibold">图片工作台</h1>
          <AccountMenu />
        </div>
      </header>

      <div className="mx-auto grid max-w-7xl gap-5 p-4 sm:p-6 lg:grid-cols-[420px_minmax(0,1fr)]">
        <form
          onSubmit={submit}
          className="h-fit space-y-5 rounded-2xl border bg-white p-5 lg:sticky lg:top-20"
        >
          <div>
            <h2 className="text-lg font-semibold">生成设置</h2>
            <p className="mt-1 text-sm text-slate-500">
              不上传来源图时是文生图；上传后自动切换为图生图。
            </p>
          </div>

          <label className="block text-sm font-medium">
            提示词
            <textarea
              name="prompt"
              required
              rows={5}
              placeholder="描述希望生成或修改的画面…"
              className="mt-2 w-full resize-none rounded-xl border p-3 text-sm outline-none focus:ring-2 focus:ring-slate-300"
            />
          </label>

          <div>
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm font-medium">来源图片（可选）</span>
              {source && (
                <button
                  type="button"
                  className="flex items-center gap-1 text-xs text-red-600"
                  onClick={() => {
                    if (sourcePreview) URL.revokeObjectURL(sourcePreview);
                    setSource(null);
                    setSourcePreview(null);
                    if (sourceInput.current) sourceInput.current.value = "";
                  }}
                >
                  <X className="size-3.5" /> 移除
                </button>
              )}
            </div>
            <button
              type="button"
              onClick={() => sourceInput.current?.click()}
              className="flex min-h-36 w-full items-center justify-center overflow-hidden rounded-xl border border-dashed bg-slate-50 hover:bg-slate-100"
            >
              {sourcePreview ? (
                <img
                  src={sourcePreview}
                  alt="来源图片预览"
                  className="max-h-64 w-full object-contain"
                />
              ) : (
                <span className="flex flex-col items-center gap-2 text-sm text-slate-500">
                  <Upload className="size-6" /> 上传 JPG、PNG 或 WebP
                </span>
              )}
            </button>
            <input
              ref={sourceInput}
              type="file"
              accept="image/jpeg,image/png,image/webp"
              className="hidden"
              onChange={chooseSource}
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <label className="text-sm font-medium">
              Provider
              <select
                name="provider"
                defaultValue="auto"
                className="mt-2 h-10 w-full rounded-lg border bg-white px-2 text-sm"
              >
                <option value="auto">自动选择</option>
                <option value="zhipu">智谱</option>
                <option value="openai">OpenAI</option>
                <option value="mock">Mock 自测</option>
              </select>
            </label>
            <label className="text-sm font-medium">
              尺寸
              <select
                name="size"
                className="mt-2 h-10 w-full rounded-lg border bg-white px-2 text-sm"
              >
                {IMAGE_SIZES.map((size) => (
                  <option key={size}>{size}</option>
                ))}
              </select>
            </label>
            <label className="text-sm font-medium">
              质量
              <select
                name="quality"
                className="mt-2 h-10 w-full rounded-lg border bg-white px-2 text-sm"
              >
                {IMAGE_QUALITIES.map((quality) => (
                  <option key={quality}>{quality}</option>
                ))}
              </select>
            </label>
            <label className="text-sm font-medium">
              模型（可选）
              <input
                name="model"
                placeholder="使用 Provider 默认值"
                className="mt-2 h-10 w-full rounded-lg border px-3 text-sm"
              />
            </label>
          </div>

          {error && (
            <p className="rounded-xl bg-red-50 p-3 text-sm text-red-700">
              {error}
            </p>
          )}
          <Button
            className="w-full"
            size="lg"
            disabled={loading}
          >
            {loading ? <LoaderCircle className="animate-spin" /> : <Sparkles />}
            {source ? "开始图生图" : "开始文生图"}
          </Button>
        </form>

        <div className="space-y-5">
          <section className="flex min-h-[460px] items-center justify-center overflow-hidden rounded-2xl border bg-white p-4">
            {resultPreview ? (
              <img
                src={resultPreview}
                alt="生成结果"
                className="max-h-[720px] w-full object-contain"
              />
            ) : (
              <div className="text-center text-slate-400">
                <ImageIcon className="mx-auto mb-3 size-12" />
                <p className="text-sm">生成结果将在这里显示</p>
              </div>
            )}
          </section>

          <section className="rounded-2xl border bg-white p-5">
            <h2 className="mb-4 font-semibold">最近生成</h2>
            {history.length === 0 ? (
              <p className="text-sm text-slate-500">还没有图片生成记录。</p>
            ) : (
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {history.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    disabled={!item.output_file_id}
                    onClick={() =>
                      item.output_file_id && loadOutput(item.output_file_id)
                    }
                    className="rounded-xl border p-3 text-left hover:bg-slate-50 disabled:opacity-60"
                  >
                    <div className="mb-2 flex items-center justify-between gap-2">
                      <span className="rounded-full bg-slate-100 px-2 py-1 text-xs">
                        {item.mode === "image_to_image" ? "图生图" : "文生图"}
                      </span>
                      <span className="text-xs text-slate-500">
                        {item.provider}
                      </span>
                    </div>
                    <p className="line-clamp-2 text-sm">{item.prompt}</p>
                    <p className="mt-2 truncate text-xs text-slate-400">
                      {item.model}
                    </p>
                  </button>
                ))}
              </div>
            )}
          </section>
        </div>
      </div>
    </main>
  );
}

export default function ImageStudioPage() {
  return (
    <AuthBoundary>
      <ImageStudioContent />
    </AuthBoundary>
  );
}
