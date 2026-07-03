#!/usr/bin/env ruby

# Count non-blank, non-comment lines in every *.py file under the CWD.
# Usage:  ruby loc.rb

require 'pathname'

def code_lines(path)
  File.foreach(path).count do |line|
    stripped = line.strip
    !stripped.empty? && !stripped.start_with?('#')
  end
end

results = []

Pathname('.').find do |p|
  next unless p.file? && p.extname == '.py'
  results << [code_lines(p), p.cleanpath]
end

results.sort_by! { |lines, _| -lines }

results.each { |lines, path| puts "%5d %s" % [lines, path] }
