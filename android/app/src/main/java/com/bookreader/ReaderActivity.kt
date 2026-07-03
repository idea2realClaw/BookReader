package com.bookreader

import android.os.Bundle
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.bookreader.databinding.ActivityReaderBinding
import com.chaquo.python.Python

class ReaderActivity : AppCompatActivity() {

    private lateinit var binding: ActivityReaderBinding
    private var currentPage = 0
    private var totalPages = 0
    private var bookPath = ""
    private var parser: Any? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityReaderBinding.inflate(layoutInflater)
        setContentView(binding.root)

        bookPath = intent.getStringExtra("book_path") ?: ""
        val bookType = intent.getStringExtra("book_type") ?: "txt"

        setupToolbar()
        loadBook(bookPath, bookType)
        setupControls()
    }

    private fun setupToolbar() {
        setSupportActionBar(binding.toolbar)
        supportActionBar?.setDisplayHomeAsUpEnabled(true)
        supportActionBar?.title = "Reading"
        binding.toolbar.setNavigationOnClickListener {
            finish()
        }
    }

    private fun loadBook(path: String, type: String) {
        try {
            val py = Python.getInstance()
            val core = py.getModule("core")
            
            // Create parser
            parser = core.callAttr("create_parser", path)
            val book = parser!!.callAttr("parse", path)
            
            totalPages = book["total_pages"].toInt()
            currentPage = book["current_page"].toInt()
            
            // Display first page
            displayPage(currentPage)
            updatePageInfo()
            
        } catch (e: Exception) {
            Toast.makeText(this, "Error loading book: ${e.message}", Toast.LENGTH_LONG).show()
            e.printStackTrace()
        }
    }

    private fun displayPage(pageNum: Int) {
        try {
            val py = Python.getInstance()
            val page = parser?.callAttr("get_page", pageNum)
            val content = page?.get("content").toString()
            
            binding.txtContent.text = content
        } catch (e: Exception) {
            Toast.makeText(this, "Error displaying page: ${e.message}", Toast.LENGTH_SHORT).show()
        }
    }

    private fun setupControls() {
        binding.btnPrev.setOnClickListener {
            if (currentPage > 0) {
                currentPage--
                displayPage(currentPage)
                updatePageInfo()
                saveProgress()
            }
        }

        binding.btnNext.setOnClickListener {
            if (currentPage < totalPages - 1) {
                currentPage++
                displayPage(currentPage)
                updatePageInfo()
                saveProgress()
            }
        }
    }

    private fun updatePageInfo() {
        binding.txtPageInfo.text = "Page ${currentPage + 1} / $totalPages"
    }

    private fun saveProgress() {
        try {
            val py = Python.getInstance()
            val core = py.getModule("core")
            val repo = core.callAttr("BookRepository")
            repo.callAttr("update_progress", bookPath, currentPage)
        } catch (e: Exception) {
            e.printStackTrace()
        }
    }
}
