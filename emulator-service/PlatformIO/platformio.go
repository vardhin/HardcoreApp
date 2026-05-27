package platformio

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
)

type File struct {
	Path    string `json:"path"`
	Content string `json:"content"`
}

type ProjectRequest struct {
	ProjectPath string `json:"projectPath"`
	Files       []File `json:"files,omitempty"`
}

func platformioCandidates() []string {
	candidates := []string{}

	if configured := os.Getenv("PLATFORMIO_CMD"); configured != "" {
		candidates = append(candidates, configured)
	}

	candidates = append(candidates, "pio", "platformio")

	if home, err := os.UserHomeDir(); err == nil {
		candidates = append(candidates,
			filepath.Join(home, ".platformio", "penv", "bin", "pio"),
			filepath.Join(home, ".platformio", "penv", "bin", "platformio"),
			filepath.Join(home, ".platformio", "penv", "Scripts", "pio.exe"),
			filepath.Join(home, ".platformio", "penv", "Scripts", "platformio.exe"),
		)
	}

	if exe, err := os.Executable(); err == nil {
		base := filepath.Dir(exe)
		candidates = append(candidates,
			filepath.Join(base, "tools", "platformio", "penv", "bin", "pio"),
			filepath.Join(base, "tools", "platformio", "penv", "Scripts", "pio.exe"),
			filepath.Join(base, "platformio", "penv", "bin", "pio"),
			filepath.Join(base, "platformio", "penv", "Scripts", "pio.exe"),
		)
	}

	return candidates
}

func platformioExecutable() (string, error) {
	for _, candidate := range platformioCandidates() {
		if candidate == "" {
			continue
		}

		if filepath.Base(candidate) == candidate {
			if resolved, err := exec.LookPath(candidate); err == nil {
				return resolved, nil
			}
			continue
		}

		if info, err := os.Stat(candidate); err == nil && !info.IsDir() {
			return candidate, nil
		}
	}

	installHint := "Install PlatformIO Core or set PLATFORMIO_CMD to the full pio executable path."
	if runtime.GOOS == "linux" || runtime.GOOS == "darwin" {
		installHint = "Install PlatformIO Core, add ~/.platformio/penv/bin to PATH, or set PLATFORMIO_CMD to the full pio executable path."
	}

	return "", errors.New("PlatformIO executable not found. " + installHint)
}

func runPIOCommand(projectPath string, args ...string) (string, error) {
	pio, err := platformioExecutable()
	if err != nil {
		return "", err
	}

	cmd := exec.Command(pio, args...)
	cmd.Dir = projectPath

	output, err := cmd.CombinedOutput()

	if err != nil && len(output) > 0 {
		return string(output), fmt.Errorf("%w: %s", err, string(output))
	}

	return string(output), err
}

func BuildProject(projectPath string) (string, error) {
	return runPIOCommand(projectPath, "run")
}

func FlashProject(projectPath string) (string, error) {
	return runPIOCommand(projectPath, "run", "-t", "upload")
}

func syncFiles(req ProjectRequest) {
	for _, file := range req.Files {
		fullPath := filepath.Join(req.ProjectPath, file.Path)
		if err := os.MkdirAll(filepath.Dir(fullPath), 0755); err == nil {
			os.WriteFile(fullPath, []byte(file.Content), 0644)
		}
	}
}

func BuildHandler(w http.ResponseWriter, r *http.Request) {
	var req ProjectRequest

	err := json.NewDecoder(r.Body).Decode(&req)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	syncFiles(req)

	output, err := BuildProject(req.ProjectPath)

	response := map[string]interface{}{
		"success": err == nil,
		"output":  output,
	}

	if err != nil {
		response["error"] = err.Error()
	}

	json.NewEncoder(w).Encode(response)
}

func FlashHandler(w http.ResponseWriter, r *http.Request) {
	var req ProjectRequest

	err := json.NewDecoder(r.Body).Decode(&req)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	syncFiles(req)

	output, err := FlashProject(req.ProjectPath)

	response := map[string]interface{}{
		"success": err == nil,
		"output":  output,
	}

	if err != nil {
		response["error"] = err.Error()
	}

	json.NewEncoder(w).Encode(response)
}
