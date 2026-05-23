package main

import (
	"fmt"
	"net/http"

	platformio "hardcore-debug/PlatformIO"
	QEMU "hardcore-debug/QEMU"
	debug "hardcore-debug/debug"
)

var dbg *debug.GDBDebugger

func ConnectHandler(
	w http.ResponseWriter,
	r *http.Request,
) {

	debugger := &debug.GDBDebugger{}

	err := debugger.Connect()

	if err != nil {

		http.Error(
			w,
			err.Error(),
			500,
		)

		return
	}

	dbg = debugger

	fmt.Fprintf(
		w,
		"Debugger Connected",
	)
}
func RegistersHandler(w http.ResponseWriter, r *http.Request) {

	regs, err := dbg.ReadRegisters()

	if err != nil {
		http.Error(w, err.Error(), 500)
		return
	}

	fmt.Fprintf(w,
		"PC: 0x%X\nSP: 0x%X\nLR: 0x%X\nXPSR: 0x%X",
		regs.PC,
		regs.SP,
		regs.LR,
		regs.XPSR,
	)
}

func HaltHandler(w http.ResponseWriter, r *http.Request) {

	err := dbg.Halt()

	if err != nil {
		http.Error(w, err.Error(), 500)
		return
	}

	w.Write([]byte("CPU Halted"))
}

func ContinueHandler(w http.ResponseWriter, r *http.Request) {

	err := dbg.Continue()

	if err != nil {
		http.Error(w, err.Error(), 500)
		return
	}

	w.Write([]byte("CPU Running"))
}

func enableCORS(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {

		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type")

		if r.Method == "OPTIONS" {
			return
		}

		next.ServeHTTP(w, r)
	})
}

func EmulateHandler(w http.ResponseWriter, r *http.Request) {

	output, err := QEMU.RunQEMU(
		"C:/Users/KI/Desktop/Hardcore_AI/Blinky/.pio/build/bluepill_f103c8/firmware.elf",
	)

	if err != nil {
		w.Write([]byte(err.Error() + "\n" + output))
		return
	}

	w.Write([]byte(output))
}
func StepHandler(
	w http.ResponseWriter,
	r *http.Request,
) {

	defer func() {

		if rec := recover(); rec != nil {

			http.Error(
				w,
				fmt.Sprintf(
					"panic: %v",
					rec,
				),
				500,
			)
		}
	}()

	err := dbg.Step()

	if err != nil {

		http.Error(
			w,
			err.Error(),
			500,
		)

		return
	}

	fmt.Fprintf(
		w,
		"CPU Stepped",
	)
}
func main() {

	http.HandleFunc("/platformio/build", platformio.BuildHandler)
	http.HandleFunc("/platformio/flash", platformio.FlashHandler)
	http.HandleFunc("/qemu/run", EmulateHandler)
	http.HandleFunc("/debug/connect", ConnectHandler)
	http.HandleFunc("/debug/registers", RegistersHandler)
	http.HandleFunc("/debug/halt", HaltHandler)
	http.HandleFunc("/debug/continue", ContinueHandler)
	http.HandleFunc(
		"/debug/step",
		StepHandler,
	)

	fmt.Println("Server running on :8080")

	err := http.ListenAndServe(
		":8080",
		enableCORS(http.DefaultServeMux),
	)

	if err != nil {
		panic(err)
	}
}
