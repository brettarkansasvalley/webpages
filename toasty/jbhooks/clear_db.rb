#!/usr/bin/env ruby

class SQLiteCleaner
  def initialize(db_file, options = {})
    @db_file = db_file
    @options = {
      dry_run: false,
      verbose: true,
      confirm: true,
      preserve_tables: ['workers', 'worker_roles', 'worker_assignments']
    }.merge(options)
  end

  def clean_database
    validate_file
    
    tables = get_table_list
    return if tables.empty?
    
    display_tables(tables)
    
    if @options[:confirm] && !@options[:dry_run]
      return unless confirm_action(tables)
    end
    
    if @options[:dry_run]
      puts "\n[DRY RUN] Would delete records from tables (excluding: #{@options[:preserve_tables].join(', ')})"
      return
    end
    
    execute_cleanup(tables)
  end

  private

  def validate_file
    unless File.exist?(@db_file)
      puts "Error: Database file '#{@db_file}' does not exist."
      exit 1
    end
    
    # Check if sqlite3 command is available
    unless system("which sqlite3 > /dev/null 2>&1")
      puts "Error: sqlite3 command not found. Please install sqlite3:"
      puts "  Ubuntu/Debian: sudo apt-get install sqlite3"
      puts "  CentOS/RHEL: sudo yum install sqlite"
      puts "  macOS: brew install sqlite"
      exit 1
    end
  end

  def get_table_list
    result = `sqlite3 #{@db_file} "SELECT name FROM sqlite_master WHERE type='table';" 2>/dev/null`
    tables = result.strip.split("\n").reject { |line| line.empty? || line.start_with?('sqlite_') }
    tables.map { |table| [table] }
  end

  def display_tables(tables)
    if @options[:verbose]
      puts "Found #{tables.length} table(s):"
      tables.each { |table| puts "  - #{table[0]}" }
      
      unless @options[:preserve_tables].empty?
        puts "\nTables that will NOT be cleared:"
        @options[:preserve_tables].each { |table| puts "  - #{table}" }
      end
    end
  end

  def confirm_action(tables)
    tables_to_clear = tables.reject { |table| @options[:preserve_tables].include?(table[0]) }
    
    puts "\nWARNING: This will permanently delete records from the following tables!"
    puts "Tables to be affected:"
    tables_to_clear.each { |table| puts "  - #{table[0]}" }
    
    unless @options[:preserve_tables].empty?
      puts "\nTables that will be preserved:"
      @options[:preserve_tables].each { |table| puts "  - #{table}" }
    end
    
    # Try to read from stdin, but handle errors gracefully
    begin
      print "\nAre you sure you want to continue? (yes/no): "
      $stdout.flush
      
      # Read input with error handling
      response = gets
      
      if response.nil?
        puts "\nNo input received. Operation cancelled."
        return false
      end
      
      response = response.chomp.downcase
      
      if response == 'yes' || response == 'y'
        return true
      else
        puts "Operation cancelled."
        return false
      end
    rescue => e
      puts "\nError reading input: #{e.message}"
      puts "Operation cancelled."
      return false
    end
  end

  def execute_cleanup(tables)
    deleted_count = 0
    preserved_count = 0
    
    puts "\nStarting cleanup..." if @options[:verbose]
    
    tables.each do |table|
      table_name = table[0]
      
      # Skip tables that should be preserved
      if @options[:preserve_tables].include?(table_name)
        if @options[:verbose]
          puts "Preserving table: #{table_name} (skipping deletion)"
        end
        preserved_count += 1
        next
      end
      
      if @options[:verbose]
        puts "Deleting all records from table: #{table_name}"
      end
      
      # Get count before deletion (for reporting)
      count_result = `sqlite3 #{@db_file} "SELECT COUNT(*) FROM #{table_name};" 2>/dev/null`
      count_before = count_result.strip.to_i
      
      # Delete all records
      delete_result = `sqlite3 #{@db_file} "DELETE FROM #{table_name};" 2>&1`
      success = $?.success?
      
      if success
        if @options[:verbose]
          puts "  Records deleted: #{count_before}"
        end
        deleted_count += count_before
      else
        puts "  Error deleting from table: #{table_name}"
        puts "  Error details: #{delete_result}" unless delete_result.empty?
      end
    end
    
    puts "\nCleanup completed successfully!"
    puts "Tables cleared: #{tables.length - preserved_count}"
    puts "Tables preserved: #{preserved_count}"
    puts "Total records deleted: #{deleted_count}"
  end
end

# Parse command line options
require 'optparse'

options = { preserve_tables: ['workers', 'worker_roles', 'worker_assignments'] }
OptionParser.new do |opts|
  opts.banner = "Usage: #{$0} [options] <database_file.sqlite>"
  opts.separator ""
  opts.separator "Options:"

  opts.on("-n", "--dry-run", "Show what would be deleted without actually doing it") do
    options[:dry_run] = true
  end

  opts.on("-q", "--quiet", "Suppress verbose output") do
    options[:verbose] = false
  end

  opts.on("-y", "--yes", "Skip confirmation prompt") do
    options[:confirm] = false
  end

  opts.on("-a", "--all", "Clear ALL tables (including preserved ones)") do
    options[:preserve_tables] = []
  end

  opts.on("-h", "--help", "Show this help message") do
    puts opts
    exit
  end
end.parse!

# Main execution
if ARGV.length != 1
  puts "Error: Please provide a database file."
  puts "Usage: #{$0} [options] <database_file.sqlite>"
  exit 1
end

db_file = ARGV[0]
cleaner = SQLiteCleaner.new(db_file, options)
cleaner.clean_database
