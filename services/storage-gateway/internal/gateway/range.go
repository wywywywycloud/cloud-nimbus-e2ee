package gateway

import (
	"errors"
	"strconv"
	"strings"
)

var errInvalidRange = errors.New("invalid byte range")

type byteRange struct {
	start int64
	end   int64
}

func parseSingleRange(header string, size int64) (byteRange, error) {
	if size < 0 || !strings.HasPrefix(header, "bytes=") || strings.Contains(header, ",") {
		return byteRange{}, errInvalidRange
	}
	spec := strings.TrimPrefix(header, "bytes=")
	startRaw, endRaw, ok := strings.Cut(spec, "-")
	if !ok || (startRaw == "" && endRaw == "") || size == 0 {
		return byteRange{}, errInvalidRange
	}
	if startRaw == "" {
		suffix, err := strconv.ParseInt(endRaw, 10, 64)
		if err != nil || suffix <= 0 {
			return byteRange{}, errInvalidRange
		}
		if suffix > size {
			suffix = size
		}
		return byteRange{start: size - suffix, end: size - 1}, nil
	}
	start, err := strconv.ParseInt(startRaw, 10, 64)
	if err != nil || start < 0 || start >= size {
		return byteRange{}, errInvalidRange
	}
	end := size - 1
	if endRaw != "" {
		end, err = strconv.ParseInt(endRaw, 10, 64)
		if err != nil || end < start {
			return byteRange{}, errInvalidRange
		}
		if end >= size {
			end = size - 1
		}
	}
	return byteRange{start: start, end: end}, nil
}
