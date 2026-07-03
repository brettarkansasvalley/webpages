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

	// Try to query submissions by form ID
	ids, err := st.QuerySubmissionsByIndex("forms:toast_labor", "", nil)
	if err != nil {
		log.Fatalf("Failed to query submissions: %v", err)
	}

	fmt.Printf("Found %d submissions for forms:toast_labor\n", len(ids))

	// Also try with just "toast_labor"
	ids2, err := st.QuerySubmissionsByIndex("toast_labor", "", nil)
	if err != nil {
		log.Printf("Failed to query submissions for toast_labor: %v", err)
	} else {
		fmt.Printf("Found %d submissions for toast_labor\n", len(ids2))
	}
}
