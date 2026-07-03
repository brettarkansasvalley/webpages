package main

import (
	"fmt"
	"log"

	"formbuilderdb/pkg/models"
	"formbuilderdb/pkg/store"
)

func main() {
	// Initialize the store
	dbRoot := "/home/ubuntu/toasty/formbuilderdb/db"
	st, err := store.New(dbRoot)
	if err != nil {
		log.Fatalf("Failed to initialize store: %v", err)
	}

	// Get all submissions
	submissions, err := st.ListSubmissions()
	if err != nil {
		log.Fatalf("Failed to list submissions: %v", err)
	}

	// Filter for toast_labor submissions
	toastLaborSubmissions := []models.Submission{}
	for _, sub := range submissions {
		if sub.FormID == "forms:toast_labor" {
			toastLaborSubmissions = append(toastLaborSubmissions, sub)
		}
	}

	fmt.Printf("Found %d toast_labor submissions to reindex\n", len(toastLaborSubmissions))

	// Reindex each toast_labor submission
	reindexed := 0
	for _, sub := range toastLaborSubmissions {
		// Acquire form lock
		unlock := st.LockForm(sub.FormID)

		// Unindex first (to clear any old indices)
		err := st.UnindexSubmission(&sub)
		if err != nil {
			log.Printf("Warning: failed to unindex submission %s: %v", sub.ID, err)
		}

		// Reindex
		err = st.IndexSubmission(&sub)
		if err != nil {
			log.Printf("Warning: failed to index submission %s: %v", sub.ID, err)
		} else {
			reindexed++
		}

		unlock()
	}

	fmt.Printf("Successfully reindexed %d toast_labor submissions\n", reindexed)
}
