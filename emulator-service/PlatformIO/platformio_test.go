package platformio

import (
	"os"
	"path/filepath"
	"testing"
)

func TestPlatformioExecutableFindsUserPenvWhenPathDoesNotContainPIO(t *testing.T) {
	home := t.TempDir()
	pioPath := filepath.Join(home, ".platformio", "penv", "bin", "pio")

	if err := os.MkdirAll(filepath.Dir(pioPath), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(pioPath, []byte("#!/bin/sh\n"), 0755); err != nil {
		t.Fatal(err)
	}

	t.Setenv("HOME", home)
	t.Setenv("PATH", "")
	t.Setenv("PLATFORMIO_CMD", "")

	got, err := platformioExecutable()
	if err != nil {
		t.Fatal(err)
	}
	if got != pioPath {
		t.Fatalf("expected %q, got %q", pioPath, got)
	}
}

func TestPlatformioExecutableReturnsHelpfulErrorWhenMissing(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	t.Setenv("PATH", "")
	t.Setenv("PLATFORMIO_CMD", "")

	if _, err := platformioExecutable(); err == nil {
		t.Fatal("expected missing PlatformIO error")
	}
}
