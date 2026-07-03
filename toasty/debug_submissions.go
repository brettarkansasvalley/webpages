package main

import (
	"fmt"
	"log"

	"formbuilderdb/pkg/store"
)

func main() {
	dbRoot := "/home/ubuntu/toasty/formbuilderdb/db"
	st, err := store.New(dbRoot)
	if err != nil {
		log.Fatalf("Failed to initialize store: %v", err)
	}

	submissions, err := st.ListSubmissions()
	if err != nil {
		log.Fatalf("Failed to list submissions: %v", err)
	}

	fmt.Printf("Total submissions found: %d\n", len(submissions))

	toastLaborCount := 0
	for _, sub := range submissions {
		if sub.FormID == "forms:toast_labor" {
			toastLaborCount++
		}
	}

	fmt.Printf("Toast labor submissions found: %d\n", toastLaborCount)
}
