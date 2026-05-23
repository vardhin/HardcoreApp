package qemu

import (
	"os"
	"os/exec"
)

func RunQEMU(firmwarePath string) (string, error) {

	cmd := exec.Command(
		"qemu-system-arm",
		"-M", "stm32vldiscovery",
		"-kernel", firmwarePath,
		"-S",
		"-gdb", "tcp::3333",
		"-nographic",
	)

	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	err := cmd.Start()

	if err != nil {
		return "", err
	}

	return "QEMU Started", nil
}
