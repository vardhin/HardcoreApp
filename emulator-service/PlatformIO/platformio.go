package platformio

import (
	"encoding/json"
	"net/http"
	"os/exec"
)

type ProjectRequest struct {
	ProjectPath string `json:"projectPath"`
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
