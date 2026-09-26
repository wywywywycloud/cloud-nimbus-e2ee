package gateway

import "testing"

func TestParseSingleRange(t *testing.T) {
	tests := []struct {
		header     string
		size       int64
		start, end int64
	}{
		{"bytes=1-3", 7, 1, 3},
		{"bytes=4-", 7, 4, 6},
		{"bytes=-2", 7, 5, 6},
		{"bytes=0-99", 7, 0, 6},
	}
	for _, test := range tests {
		selected, err := parseSingleRange(test.header, test.size)
		if err != nil || selected.start != test.start || selected.end != test.end {
			t.Fatalf("%s: got %#v, %v", test.header, selected, err)
		}
	}
	for _, header := range []string{"bytes=", "items=1-2", "bytes=8-9", "bytes=1-2,4-5", "bytes=-0"} {
		if _, err := parseSingleRange(header, 7); err == nil {
			t.Fatalf("invalid range accepted: %s", header)
		}
	}
}
