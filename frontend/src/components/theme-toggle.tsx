"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

const THEMES = ["light", "dark", "system"] as const;
type Theme = (typeof THEMES)[number];

const themeDetails: Record<
  Theme,
  { label: string; icon: typeof Sun }
> = {
  light: { label: "浅色模式", icon: Sun },
  dark: { label: "深色模式", icon: Moon },
  system: { label: "跟随系统", icon: Monitor },
};

export function ThemeToggle() {
  const { theme = "system", setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

  const currentTheme = THEMES.includes(theme as Theme)
    ? (theme as Theme)
    : "system";
  const nextTheme = THEMES[(THEMES.indexOf(currentTheme) + 1) % THEMES.length];
  const CurrentIcon = themeDetails[currentTheme].icon;

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="size-8 rounded-lg"
          onClick={() => setTheme(nextTheme)}
          aria-label={
            mounted
              ? `${themeDetails[currentTheme].label}，点击切换至${themeDetails[nextTheme].label}`
              : "切换主题"
          }
        >
          {mounted ? <CurrentIcon className="size-4" /> : <Sun className="size-4" />}
        </Button>
      </TooltipTrigger>
      <TooltipContent side="bottom">
        {mounted ? themeDetails[currentTheme].label : "切换主题"}
      </TooltipContent>
    </Tooltip>
  );
}
