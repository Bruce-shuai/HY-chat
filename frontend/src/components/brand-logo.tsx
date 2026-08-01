import { cn } from "@/lib/utils";

type BrandLogoProps = {
  variant?: "mark" | "wordmark";
  className?: string;
  priority?: boolean;
};

export function BrandLogo({
  variant = "mark",
  className,
  priority = false,
}: BrandLogoProps) {
  return (
    <span
      className={cn(
        "shrink-0",
        variant === "mark"
          ? "relative inline-block size-8 overflow-hidden rounded-sm bg-white"
          : "inline-flex items-center gap-3",
        className,
      )}
      role="img"
      aria-label="HY-Agent"
    >
      <img
        src="/hy-agent-mark.webp"
        alt=""
        aria-hidden="true"
        loading={priority ? "eager" : "lazy"}
        fetchPriority={priority ? "high" : "auto"}
        width={256}
        height={256}
        className={cn(
          "object-contain select-none",
          variant === "mark" ? "size-full" : "size-12 rounded-xl bg-white",
        )}
      />
      {variant === "wordmark" ? (
        <span
          aria-hidden="true"
          className="text-2xl font-semibold tracking-tight whitespace-nowrap"
        >
          HY-Agent
        </span>
      ) : null}
    </span>
  );
}
