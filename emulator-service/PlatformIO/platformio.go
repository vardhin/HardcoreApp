package platformio

import (
	"encoding/json"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
)

type File struct {
	Path    string `json:"path"`
	Content string `json:"content"`
}

type ProjectRequest struct {
	ProjectPath string `json:"projectPath"`
	Files       []File `json:"files,omitempty"`
}

func runPIOCommand(projectPath string, args ...string) (string, error) {
	cmd := exec.Command("pio", args...)
	cmd.Dir = projectPath

	output, err := cmd.CombinedOutput()

	return string(output), err
}

func BuildProject(projectPath string) (string, error) {
	return runPIOCommand(projectPath, "run")
}

func FlashProject(projectPath string) (string, error) {
	return runPIOCommand(projectPath, "run", "-t", "upload")
}

func BuildHandler(w http.ResponseWriter, r *http.Request) {
	var req ProjectRequest

	err := json.NewDecoder(r.Body).Decode(&req)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	for _, file := range req.Files {
		fullPath := filepath.Join(req.ProjectPath, file.Path)
		if err := os.MkdirAll(filepath.Dir(fullPath), 0755); err == nil {
			os.WriteFile(fullPath, []byte(file.Content), 0644)
		}
	}

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
