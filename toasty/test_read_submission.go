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

	// Try to read a specific toast_labor submission
	sub, err := st.GetSubmission("submissions:3809969e07b94eaa85a5e26364bc6cfa")
	if err != nil {
		log.Fatalf("Failed to get submission: %v", err)
	}

	fmt.Printf("Found submission: %+v\n", sub)
	fmt.Printf("Form ID: %s\n", sub.FormID)
	fmt.Printf("Version: %d\n", sub.Version)
}
