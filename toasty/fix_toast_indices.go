package main

import (
	"fmt"
	"log"
	"strings"

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

	// Filter for toast submissions
	toastSubmissions := []models.Submission{}
	for _, sub := range submissions {
		if strings.Contains(sub.FormID, "toast") {
			toastSubmissions = append(toastSubmissions, sub)
		}
	}

	fmt.Printf("Found %d toast submissions to reindex\n", len(toastSubmissions))

	// Reindex each toast submission
	reindexed := 0
	for _, sub := range toastSubmissions {
		// Acquire form lock
		unlock := st.LockForm(sub.FormID)

		// Unindex first (to clear old indices)
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

	fmt.Printf("Successfully reindexed %d toast submissions\n", reindexed)
}
