import { Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { type Theme, currentTheme, preferredTheme, toggleTheme } from "@/lib/theme";

export function ThemeToggle({ className }: { className?: string }) {
  const [theme, setTheme] = useState<Theme>("light");

  useEffect(() => {
    const preferred = preferredTheme();
    document.documentElement.classList.toggle("dark", preferred === "dark");
    setTheme(currentTheme());
  }, []);

  const next = theme === "dark" ? "light" : "dark";

  return (
    <Button
      variant="ghost"
      size="icon"
      className={className}
      title={`Switch to ${next} theme`}
      aria-label={`Switch to ${next} theme`}
      onClick={() => setTheme(toggleTheme())}
    >
      {next === "dark" ? <Moon aria-hidden="true" /> : <Sun aria-hidden="true" />}
    </Button>
  );
}
