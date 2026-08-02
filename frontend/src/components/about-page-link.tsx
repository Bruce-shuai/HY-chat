import Link from "next/link";
import { UserRound } from "lucide-react";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

export function AboutPageLink({ className }: { className?: string }) {
  return (
    <Button
      asChild
      variant="ghost"
      size="sm"
      className={cn("h-10 shrink-0 rounded-xl px-2.5 sm:px-3", className)}
    >
      <Link
        href="/about"
        aria-label="进入关于作者页面"
        title="关于作者"
      >
        <UserRound className="size-4" />
        <span className="hidden sm:inline">关于作者</span>
      </Link>
    </Button>
  );
}
