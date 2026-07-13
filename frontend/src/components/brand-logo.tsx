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
        "relative inline-block shrink-0 overflow-hidden bg-white",
        variant === "mark"
          ? "size-8 rounded-sm"
          : "h-28 w-32 rounded-2xl",
        className,
      )}
      role="img"
      aria-label="HY-chat"
    >
      {variant === "mark" ? (
        <svg
          viewBox="372 275 510 510"
          className="size-full select-none"
          aria-hidden="true"
        >
          <image
            href="/hy-chat-logo.png"
            width="1254"
            height="1254"
          />
        </svg>
      ) : (
        <img
          src="/hy-chat-logo.png"
          alt=""
          aria-hidden="true"
          loading={priority ? "eager" : "lazy"}
          fetchPriority={priority ? "high" : "auto"}
          className="absolute top-1/2 left-1/2 h-auto w-[155%] max-w-none -translate-x-1/2 -translate-y-1/2 select-none"
        />
      )}
    </span>
  );
}
